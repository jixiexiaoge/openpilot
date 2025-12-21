#include <cassert>
#include <unordered_set>
#include <sstream>
#include <cctype>

#include "cereal/messaging/msgq_to_zmq.h"
#include "cereal/services.h"
#include "common/util.h"

ExitHandler do_exit;

static std::unordered_set<std::string> parse_whitelist(const std::string& s) {
  std::unordered_set<std::string> out;
  std::string token;
  token.reserve(s.size());

  auto flush = [&]() {
    if (!token.empty()) {
      out.insert(token);
      token.clear();
    }
    };

  for (char c : s) {
    // 구분자: 콤마/공백/탭/세미콜론/파이프 등
    if (std::isspace((unsigned char)c) || c == ',' || c == ';' || c == '|') {
      flush();
    }
    else {
      token.push_back(c);
    }
  }
  flush();
  return out;
}

static std::vector<std::string> get_services(const std::string& whitelist_str, bool /*zmq_to_msgq*/) {
  std::vector<std::string> service_list;

  const bool use_filter = !whitelist_str.empty();
  std::unordered_set<std::string> whitelist = use_filter ? parse_whitelist(whitelist_str)
    : std::unordered_set<std::string>{};

  for (const auto& it : services) {
    const std::string& name = it.second.name;
    if (use_filter && whitelist.find(name) == whitelist.end()) continue;
    service_list.push_back(name);
  }
  return service_list;
}


void msgq_to_zmq(const std::vector<std::string> &endpoints, const std::string &ip) {
  MsgqToZmq bridge;
  bridge.run(endpoints, ip);
}

void zmq_to_msgq(const std::vector<std::string> &endpoints, const std::string &ip) {
  auto poller = std::make_unique<ZMQPoller>();
  auto pub_context = std::make_unique<MSGQContext>();
  auto sub_context = std::make_unique<ZMQContext>();
  std::map<SubSocket *, PubSocket *> sub2pub;

  for (auto endpoint : endpoints) {
    auto pub_sock = new MSGQPubSocket();
    auto sub_sock = new ZMQSubSocket();
    pub_sock->connect(pub_context.get(), endpoint);
    sub_sock->connect(sub_context.get(), endpoint, ip, false);

    poller->registerSocket(sub_sock);
    sub2pub[sub_sock] = pub_sock;
  }

  while (!do_exit) {
    for (auto sub_sock : poller->poll(100)) {
      std::unique_ptr<Message> msg(sub_sock->receive(true));
      if (msg) {
        sub2pub[sub_sock]->sendMessage(msg.get());
      }
    }
  }

  // Clean up allocated sockets
  for (auto &[sub_sock, pub_sock] : sub2pub) {
    delete sub_sock;
    delete pub_sock;
  }
}

int main(int argc, char **argv) {
  bool is_zmq_to_msgq = argc > 3;
  std::string ip = argc > 2 ? argv[1] : "127.0.0.1";
  std::string whitelist_str = argc > 2 ? std::string(argv[2]) : "";
  std::vector<std::string> endpoints = get_services(whitelist_str, is_zmq_to_msgq);

  if (is_zmq_to_msgq) {
    zmq_to_msgq(endpoints, ip);
  } else {
    msgq_to_zmq(endpoints, ip);
  }
  return 0;
}
