#include <algorithm>
#include <cassert>
#include <cmath>

#include "system/loggerd/video_writer.h"
#include "common/swaglog.h"
#include "common/util.h"

static void configure_video_stream(AVStream *stream, const AVCodecContext *codec_ctx, uint8_t *extradata, int extradata_size) {
  if (stream->codecpar == nullptr) {
    stream->codecpar = avcodec_parameters_alloc();
    assert(stream->codecpar != nullptr);
  }
  AVCodecParameters *codecpar = stream->codecpar;
  codecpar->codec_type = codec_ctx->codec_type;
  codecpar->codec_id = codec_ctx->codec_id;
  codecpar->format = codec_ctx->pix_fmt;
  codecpar->width = codec_ctx->width;
  codecpar->height = codec_ctx->height;
  codecpar->bit_rate = codec_ctx->bit_rate;

  stream->time_base = codec_ctx->time_base;
  stream->avg_frame_rate = AVRational{codec_ctx->time_base.den, codec_ctx->time_base.num};

  if (extradata != nullptr && extradata_size > 0) {
    codecpar->extradata = (uint8_t *)av_mallocz(extradata_size + AV_INPUT_BUFFER_PADDING_SIZE);
    assert(codecpar->extradata != nullptr);
    codecpar->extradata_size = extradata_size;
    memcpy(codecpar->extradata, extradata, extradata_size);
  }
}

static const AVSampleFormat kPreferredAudioSampleFormats[] = {
  AV_SAMPLE_FMT_FLTP,
  AV_SAMPLE_FMT_FLT,
  AV_SAMPLE_FMT_S16P,
  AV_SAMPLE_FMT_S16,
};

static const AVSampleFormat *get_supported_audio_sample_formats(const AVCodec *codec) {
  if (codec == nullptr) {
    return nullptr;
  }
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
  return codec->sample_fmts;
#pragma clang diagnostic pop
}

static AVSampleFormat pick_audio_sample_format(const AVCodec *codec) {
  const AVSampleFormat *sample_fmts = get_supported_audio_sample_formats(codec);
  if (sample_fmts == nullptr) {
    return AV_SAMPLE_FMT_NONE;
  }

  for (AVSampleFormat preferred_fmt : kPreferredAudioSampleFormats) {
    for (const AVSampleFormat *fmt = sample_fmts; *fmt != AV_SAMPLE_FMT_NONE; ++fmt) {
      if (*fmt == preferred_fmt) {
        return preferred_fmt;
      }
    }
  }

  return sample_fmts[0];
}

static std::string audio_sample_format_name(AVSampleFormat fmt) {
  const char *name = av_get_sample_fmt_name(fmt);
  return name != nullptr ? name : "unknown";
}

static void disable_audio_stream(AVCodecContext **audio_codec_ctx, AVFrame **audio_frame, AVStream **audio_stream,
                                 int *audio_stream_index, std::deque<float> *audio_buffer, bool *audio_failed) {
  if (*audio_frame != nullptr) {
    av_frame_free(audio_frame);
  }
  if (*audio_codec_ctx != nullptr) {
    avcodec_free_context(audio_codec_ctx);
  }
  *audio_stream = nullptr;
  *audio_stream_index = -1;
  audio_buffer->clear();
  *audio_failed = true;
}

static void configure_audio_stream(AVStream *stream, const AVCodecContext *codec_ctx) {
  AVCodecParameters *codecpar = stream->codecpar;
  codecpar->codec_type = codec_ctx->codec_type;
  codecpar->codec_id = codec_ctx->codec_id;
  codecpar->format = codec_ctx->sample_fmt;
  codecpar->bit_rate = codec_ctx->bit_rate;
  codecpar->sample_rate = codec_ctx->sample_rate;
#if LIBAVUTIL_VERSION_MAJOR >= 57
  codecpar->ch_layout = codec_ctx->ch_layout;
#else
  codecpar->channel_layout = codec_ctx->channel_layout;
  codecpar->channels = codec_ctx->channels;
#endif
  if (codec_ctx->extradata != nullptr && codec_ctx->extradata_size > 0) {
    codecpar->extradata = (uint8_t *)av_mallocz(codec_ctx->extradata_size + AV_INPUT_BUFFER_PADDING_SIZE);
    assert(codecpar->extradata != nullptr);
    codecpar->extradata_size = codec_ctx->extradata_size;
    memcpy(codecpar->extradata, codec_ctx->extradata, codec_ctx->extradata_size);
  }
  stream->time_base = codec_ctx->time_base;
}

static bool fill_audio_frame_samples(AVFrame *frame, const std::deque<float> &audio_buffer, int sample_count) {
  auto clamp_to_i16 = [](float sample) -> int16_t {
    const float clamped = std::clamp(sample, -1.0f, 1.0f);
    return static_cast<int16_t>(std::lrint(clamped * 32767.0f));
  };

  switch (static_cast<AVSampleFormat>(frame->format)) {
    case AV_SAMPLE_FMT_FLTP:
    case AV_SAMPLE_FMT_FLT: {
      float *samples = reinterpret_cast<float *>(frame->data[0]);
      std::copy(audio_buffer.begin(), audio_buffer.begin() + sample_count, samples);
      return true;
    }
    case AV_SAMPLE_FMT_S16P:
    case AV_SAMPLE_FMT_S16: {
      int16_t *samples = reinterpret_cast<int16_t *>(frame->data[0]);
      std::transform(audio_buffer.begin(), audio_buffer.begin() + sample_count, samples, clamp_to_i16);
      return true;
    }
    default:
      return false;
  }
}

#if LIBAVUTIL_VERSION_MAJOR >= 57
static void set_mono_channel_layout(AVCodecContext *codec_ctx) {
  codec_ctx->ch_layout.order = AV_CHANNEL_ORDER_NATIVE;
  codec_ctx->ch_layout.nb_channels = 1;
  codec_ctx->ch_layout.u.mask = AV_CH_LAYOUT_MONO;
}

static void set_frame_channel_layout(AVFrame *frame, const AVCodecContext *codec_ctx) {
  frame->ch_layout = codec_ctx->ch_layout;
}
#else
static void set_mono_channel_layout(AVCodecContext *codec_ctx) {
  codec_ctx->channel_layout = AV_CH_LAYOUT_MONO;
}

static void set_frame_channel_layout(AVFrame *frame, const AVCodecContext *codec_ctx) {
  frame->channel_layout = codec_ctx->channel_layout;
}
#endif

VideoWriter::VideoWriter(const char *path, const char *filename, bool remuxing, int width, int height, int fps, cereal::EncodeIndex::Type codec)
  : remuxing(remuxing) {
  vid_path = util::string_format("%s/%s", path, filename);
  lock_path = util::string_format("%s/%s.lock", path, filename);

  int lock_fd = HANDLE_EINTR(open(lock_path.c_str(), O_RDWR | O_CREAT, 0664));
  assert(lock_fd >= 0);
  close(lock_fd);

  LOGD("encoder_open %s remuxing:%d", this->vid_path.c_str(), this->remuxing);
  if (this->remuxing) {
    bool raw = (codec == cereal::EncodeIndex::Type::BIG_BOX_LOSSLESS);
    avformat_alloc_output_context2(&this->ofmt_ctx, NULL, raw ? "matroska" : NULL, this->vid_path.c_str());
    assert(this->ofmt_ctx);

    // set codec correctly. needed?
    assert(codec != cereal::EncodeIndex::Type::FULL_H_E_V_C);
    const AVCodec *avcodec = avcodec_find_encoder(raw ? AV_CODEC_ID_FFVHUFF : AV_CODEC_ID_H264);
    assert(avcodec);

    this->codec_ctx = avcodec_alloc_context3(avcodec);
    assert(this->codec_ctx);
    this->codec_ctx->width = width;
    this->codec_ctx->height = height;
    this->codec_ctx->pix_fmt = AV_PIX_FMT_YUV420P;
    this->codec_ctx->time_base = (AVRational){ 1, fps };

    if (codec == cereal::EncodeIndex::Type::BIG_BOX_LOSSLESS) {
      // without this, there's just noise
      int err = avcodec_open2(this->codec_ctx, avcodec, NULL);
      assert(err >= 0);
    }

    this->out_stream = avformat_new_stream(this->ofmt_ctx, raw ? avcodec : NULL);
    assert(this->out_stream);
    this->out_stream_index = 0;

    int err = avio_open(&this->ofmt_ctx->pb, this->vid_path.c_str(), AVIO_FLAG_WRITE);
    assert(err >= 0);

  } else {
    this->of = util::safe_fopen(this->vid_path.c_str(), "wb");
    assert(this->of);
  }
}

void VideoWriter::initialize_audio(int sample_rate) {
  if (this->audio_failed || this->audio_initialized) {
    return;
  }

  if (this->ofmt_ctx->oformat->audio_codec == AV_CODEC_ID_NONE) {
    LOGW("audio mux unavailable for %s, continuing without audio", this->vid_path.c_str());
    this->audio_failed = true;
    return;
  }

  const AVCodec *audio_avcodec = avcodec_find_encoder(AV_CODEC_ID_AAC);
  if (audio_avcodec == nullptr) {
    LOGW("audio init disabled for %s: AAC encoder unavailable, continuing without audio", this->vid_path.c_str());
    this->audio_failed = true;
    return;
  }

  this->audio_codec_ctx = avcodec_alloc_context3(audio_avcodec);
  if (this->audio_codec_ctx == nullptr) {
    LOGW("audio init disabled for %s: failed to allocate AAC codec context, continuing without audio", this->vid_path.c_str());
    this->audio_failed = true;
    return;
  }

  this->audio_codec_ctx->sample_fmt = pick_audio_sample_format(audio_avcodec);
  if (this->audio_codec_ctx->sample_fmt == AV_SAMPLE_FMT_NONE) {
    LOGW("audio init disabled for %s: no supported AAC sample format, continuing without audio", this->vid_path.c_str());
    disable_audio_stream(&this->audio_codec_ctx, &this->audio_frame, &this->audio_stream, &this->audio_stream_index,
                         &this->audio_buffer, &this->audio_failed);
    return;
  }
  this->audio_codec_ctx->sample_rate = sample_rate;
  set_mono_channel_layout(this->audio_codec_ctx);
  this->audio_codec_ctx->bit_rate = 32000;
  this->audio_codec_ctx->flags |= AV_CODEC_FLAG_GLOBAL_HEADER;
  this->audio_codec_ctx->time_base = (AVRational){1, audio_codec_ctx->sample_rate};

  if (util::getenv("LOGGERD_TEST_AUDIO_INIT_FAIL", 0) == 1) {
    LOGW("audio init disabled for %s: forced test failure, continuing without audio", this->vid_path.c_str());
    disable_audio_stream(&this->audio_codec_ctx, &this->audio_frame, &this->audio_stream, &this->audio_stream_index,
                         &this->audio_buffer, &this->audio_failed);
    return;
  }

  int err = avcodec_open2(this->audio_codec_ctx, audio_avcodec, NULL);
  if (err < 0) {
    LOGW("audio init disabled for %s: AAC encoder rejected sample format %s (err=%d), continuing without audio",
         this->vid_path.c_str(), audio_sample_format_name(this->audio_codec_ctx->sample_fmt).c_str(), err);
    disable_audio_stream(&this->audio_codec_ctx, &this->audio_frame, &this->audio_stream, &this->audio_stream_index,
                         &this->audio_buffer, &this->audio_failed);
    return;
  }
  av_log_set_level(AV_LOG_WARNING); // hide "QAvg" info msgs at the end of every segment

  this->audio_stream = avformat_new_stream(this->ofmt_ctx, NULL);
  if (this->audio_stream == nullptr) {
    LOGW("audio init disabled for %s: failed to create audio stream, continuing without audio", this->vid_path.c_str());
    disable_audio_stream(&this->audio_codec_ctx, &this->audio_frame, &this->audio_stream, &this->audio_stream_index,
                         &this->audio_buffer, &this->audio_failed);
    return;
  }
  this->audio_stream_index = 1;
  configure_audio_stream(this->audio_stream, this->audio_codec_ctx);

  this->audio_frame = av_frame_alloc();
  if (this->audio_frame == nullptr) {
    LOGW("audio init disabled for %s: failed to allocate audio frame, continuing without audio", this->vid_path.c_str());
    disable_audio_stream(&this->audio_codec_ctx, &this->audio_frame, &this->audio_stream, &this->audio_stream_index,
                         &this->audio_buffer, &this->audio_failed);
    return;
  }
  this->audio_frame->format = this->audio_codec_ctx->sample_fmt;
  set_frame_channel_layout(this->audio_frame, this->audio_codec_ctx);
  this->audio_frame->sample_rate = this->audio_codec_ctx->sample_rate;
  this->audio_frame->nb_samples = this->audio_codec_ctx->frame_size;
  err = av_frame_get_buffer(this->audio_frame, 0);
  if (err < 0) {
    LOGW("audio init disabled for %s: failed to allocate audio frame buffer (err=%d), continuing without audio",
         this->vid_path.c_str(), err);
    disable_audio_stream(&this->audio_codec_ctx, &this->audio_frame, &this->audio_stream, &this->audio_stream_index,
                         &this->audio_buffer, &this->audio_failed);
    return;
  }

  this->audio_initialized = true;
}

void VideoWriter::write(uint8_t *data, int len, long long timestamp, bool codecconfig, bool keyframe) {
  if (of && data) {
    size_t written = util::safe_fwrite(data, 1, len, of);
    if (written != len) {
      LOGE("failed to write file.errno=%d", errno);
    }
  }

  if (remuxing) {
    if (codecconfig) {
      if (len > 0) {
        codec_ctx->extradata = (uint8_t*)av_mallocz(len + AV_INPUT_BUFFER_PADDING_SIZE);
        assert(codec_ctx->extradata != nullptr);
        codec_ctx->extradata_size = len;
        memcpy(codec_ctx->extradata, data, len);
      }
      configure_video_stream(out_stream, codec_ctx, codec_ctx->extradata, codec_ctx->extradata_size);
      // if there is an audio stream, it must be initialized before this point
      int err = avformat_write_header(ofmt_ctx, NULL);
      assert(err >= 0);
      header_written = true;
    } else {
      // input timestamps are in microseconds
      AVRational in_timebase = {1, 1000000};

      AVPacket pkt = {};
      pkt.data = data;
      pkt.size = len;
      pkt.stream_index = this->out_stream_index;

      enum AVRounding rnd = static_cast<enum AVRounding>(AV_ROUND_NEAR_INF|AV_ROUND_PASS_MINMAX);
      pkt.pts = pkt.dts = av_rescale_q_rnd(timestamp, in_timebase, out_stream->time_base, rnd);
      pkt.duration = av_rescale_q(50*1000, in_timebase, out_stream->time_base);

      if (keyframe) {
        pkt.flags |= AV_PKT_FLAG_KEY;
      }

      // TODO: can use av_write_frame for non raw?
      int err = av_interleaved_write_frame(ofmt_ctx, &pkt);
      if (err < 0) { LOGW("ts encoder write issue len: %d ts: %lld", len, timestamp); }

      av_packet_unref(&pkt);
    }
  }
}

void VideoWriter::write_audio(uint8_t *data, int len, long long timestamp, int sample_rate) {
  if (!remuxing || audio_failed) return;
  if (!audio_initialized) {
    initialize_audio(sample_rate);
  }
  if (!audio_initialized || !audio_codec_ctx || !audio_frame) return;
  // sync logMonoTime of first audio packet with the timestampEof of first video packet
  if (audio_pts == 0) {
    audio_pts = (timestamp * audio_codec_ctx->sample_rate) / 1000000ULL;
  }

  // convert s16le samples to fltp and add to buffer
  const int16_t *raw_samples = reinterpret_cast<const int16_t*>(data);
  int sample_count = len / sizeof(int16_t);
  constexpr float normalizer = 1.0f / 32768.0f;

  const size_t max_buffer_size = sample_rate * 10; // 10 seconds
  if (audio_buffer.size() + sample_count > max_buffer_size) {
    size_t samples_to_drop = (audio_buffer.size() + sample_count) - max_buffer_size;
    LOGE("Audio buffer overflow, dropping %zu oldest samples", samples_to_drop);
    audio_buffer.erase(audio_buffer.begin(), audio_buffer.begin() + samples_to_drop);
    audio_pts += samples_to_drop;
  }

  // Add new samples to the buffer
  const size_t original_size = audio_buffer.size();
  audio_buffer.resize(original_size + sample_count);
  std::transform(raw_samples, raw_samples + sample_count, audio_buffer.begin() + original_size,
                [](int16_t sample) { return sample * normalizer; });

  if (!header_written) return; // header not written yet, process audio frame after header is written
  while (audio_buffer.size() >= audio_codec_ctx->frame_size) {
    audio_frame->pts = audio_pts;
    if (!fill_audio_frame_samples(audio_frame, audio_buffer, audio_codec_ctx->frame_size)) {
      LOGW("audio init disabled for %s: unsupported audio sample format %s during frame write, continuing without audio",
           this->vid_path.c_str(), audio_sample_format_name(static_cast<AVSampleFormat>(audio_frame->format)).c_str());
      disable_audio_stream(&this->audio_codec_ctx, &this->audio_frame, &this->audio_stream, &this->audio_stream_index,
                           &this->audio_buffer, &this->audio_failed);
      return;
    }
    audio_buffer.erase(audio_buffer.begin(), audio_buffer.begin() + audio_codec_ctx->frame_size);
    encode_and_write_audio_frame(audio_frame);
  }
}

void VideoWriter::encode_and_write_audio_frame(AVFrame* frame) {
  if (!remuxing || !audio_codec_ctx) return;
  int send_result = avcodec_send_frame(audio_codec_ctx, frame); // encode frame
  if (send_result >= 0) {
    AVPacket *pkt = av_packet_alloc();
    while (avcodec_receive_packet(audio_codec_ctx, pkt) == 0) {
      av_packet_rescale_ts(pkt, audio_codec_ctx->time_base, audio_stream->time_base);
      pkt->stream_index = audio_stream_index;

      int err = av_interleaved_write_frame(ofmt_ctx, pkt); // write encoded frame
      if (err < 0) {
        LOGW("AUDIO: Write frame failed - error: %d", err);
      }
      av_packet_unref(pkt);
    }
    av_packet_free(&pkt);
  } else {
    LOGW("AUDIO: Failed to send audio frame to encoder: %d", send_result);
  }
  audio_pts += audio_codec_ctx->frame_size;
}

void VideoWriter::process_remaining_audio() {
  if (audio_codec_ctx == nullptr || audio_frame == nullptr) return;

  // Process remaining audio samples by padding with silence
  if (audio_buffer.size() > 0 && audio_buffer.size() < audio_codec_ctx->frame_size) {
    audio_buffer.resize(audio_codec_ctx->frame_size, 0.0f);

    // Encode final frame
    audio_frame->pts = audio_pts;
    if (!fill_audio_frame_samples(audio_frame, audio_buffer, audio_codec_ctx->frame_size)) {
      LOGW("audio init disabled for %s: unsupported audio sample format %s during flush, dropping remaining audio",
           this->vid_path.c_str(), audio_sample_format_name(static_cast<AVSampleFormat>(audio_frame->format)).c_str());
      return;
    }
    encode_and_write_audio_frame(audio_frame);
  }
}

VideoWriter::~VideoWriter() {
  if (this->remuxing) {
    if (this->audio_codec_ctx) {
      process_remaining_audio();
      encode_and_write_audio_frame(NULL); // flush encoder
      avcodec_free_context(&this->audio_codec_ctx);
    }
    int err = av_write_trailer(this->ofmt_ctx);
    if (err != 0) LOGE("av_write_trailer failed %d", err);
    avcodec_free_context(&this->codec_ctx);
    if (this->audio_frame) av_frame_free(&this->audio_frame);
    err = avio_closep(&this->ofmt_ctx->pb);
    if (err != 0) LOGE("avio_closep failed %d", err);
    avformat_free_context(this->ofmt_ctx);
  } else {
    util::safe_fflush(this->of);
    fclose(this->of);
    this->of = nullptr;
  }
  unlink(this->lock_path.c_str());
}
