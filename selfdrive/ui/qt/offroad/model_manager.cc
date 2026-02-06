#include "selfdrive/ui/qt/offroad/model_manager.h"

#include <openssl/evp.h>
#include <openssl/x509.h>

#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QProcess>
#include <QCryptographicHash>
#include <QStorageInfo>
#include <QRegularExpression>
#include <QUrl>
#include <QTimer>
#include <QScroller>
#include <QScrollerProperties>

#include "common/params.h"
#include "common/keys.h"
#include "system/hardware/hw.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <memory>

const QString MODELS_JSON_URL =
    "https://raw.githubusercontent.com/happymaj11r/openpilot-models/main/models.json";
const QString MODELS_DIR = "/data/models";
const QString MODELS_TMP_DIR = "/data/models_tmp";
const QString MODELS_BACKUP_DIR = "/data/models_backup";

namespace {

constexpr int ED25519_PUBLIC_KEY_LEN = 32;
constexpr int ED25519_SIGNATURE_LEN = 64;

const QStringList REQUIRED_MODEL_FILES = {
  "driving_vision_tinygrad.pkl",
  "driving_policy_tinygrad.pkl",
  "driving_vision_metadata.pkl",
  "driving_policy_metadata.pkl",
};

bool hasValidCustomModel(const QString &dir) {
  for (const QString &filename : REQUIRED_MODEL_FILES) {
    QFileInfo fi(dir + "/" + filename);
    if (!fi.exists() || fi.size() <= 0) return false;
  }
  return true;
}

QByteArray jsonDumpsString(const QString &s) {
  QString out;
  out.reserve(s.size() + 2);
  out.append('\"');
  for (QChar ch : s) {
    const ushort u = ch.unicode();
    switch (u) {
      case '\"': out.append("\\\""); break;
      case '\\': out.append("\\\\"); break;
      case '\b': out.append("\\b"); break;
      case '\f': out.append("\\f"); break;
      case '\n': out.append("\\n"); break;
      case '\r': out.append("\\r"); break;
      case '\t': out.append("\\t"); break;
      default:
        if (u <= 0x1F) {
          out.append(QString("\\u%1").arg(u, 4, 16, QLatin1Char('0')));
        } else {
          out.append(ch);
        }
    }
  }
  out.append('\"');
  return out.toUtf8();
}

std::unique_ptr<EVP_PKEY, decltype(&EVP_PKEY_free)> parseEd25519PublicKey(const QByteArray &publicKeyBytes) {
  std::unique_ptr<EVP_PKEY, decltype(&EVP_PKEY_free)> pkey(nullptr, EVP_PKEY_free);
  if (publicKeyBytes.size() == ED25519_PUBLIC_KEY_LEN) {
    pkey.reset(EVP_PKEY_new_raw_public_key(EVP_PKEY_ED25519, nullptr,
                                          reinterpret_cast<const unsigned char *>(publicKeyBytes.constData()),
                                          publicKeyBytes.size()));
    return pkey;
  }

  const unsigned char *p = reinterpret_cast<const unsigned char *>(publicKeyBytes.constData());
  EVP_PKEY *derKey = d2i_PUBKEY(nullptr, &p, publicKeyBytes.size());
  if (!derKey) return pkey;
  if (EVP_PKEY_base_id(derKey) != EVP_PKEY_ED25519) {
    EVP_PKEY_free(derKey);
    return pkey;
  }

  pkey.reset(derKey);
  return pkey;
}

bool verifyEd25519Signature(const QByteArray &message, const QByteArray &signature, EVP_PKEY *publicKey) {
  if (!publicKey) return false;
  if (signature.size() != ED25519_SIGNATURE_LEN) return false;

  std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)> ctx(EVP_MD_CTX_new(), EVP_MD_CTX_free);
  if (!ctx) return false;

  if (EVP_DigestVerifyInit(ctx.get(), nullptr, nullptr, nullptr, publicKey) != 1) return false;
  const int ret = EVP_DigestVerify(ctx.get(),
                                  reinterpret_cast<const unsigned char *>(signature.constData()),
                                  signature.size(),
                                  reinterpret_cast<const unsigned char *>(message.constData()),
                                  message.size());
  return ret == 1;
}

}  // namespace

ModelManagerDialog::ModelManagerDialog(QWidget *parent) : DialogBase(parent) {
  setWindowTitle(tr("Model Manager"));
  setMinimumSize(800, 600);

  networkManager = new QNetworkAccessManager(this);
  currentReply = nullptr;
  currentFileIndex = 0;
  isDownloading = false;

  setupUI();
  showCurrentModelInfo();
  fetchModelList();
}

void ModelManagerDialog::setupUI() {
  mainLayout = new QVBoxLayout(this);
  mainLayout->setSpacing(20);
  mainLayout->setContentsMargins(40, 40, 40, 40);

  // 현재 모델 상태
  currentModelLabel = new QLabel(this);
  currentModelLabel->setStyleSheet("font-size: 45px; font-weight: bold;");
  mainLayout->addWidget(currentModelLabel);

  // 디스크 여유 공간
  diskUsageLabel = new QLabel(this);
  diskUsageLabel->setStyleSheet("font-size: 35px; color: #888;");
  mainLayout->addWidget(diskUsageLabel);

  // 상태 라벨
  statusLabel = new QLabel(tr("Loading model list..."), this);
  statusLabel->setStyleSheet("font-size: 35px;");
  mainLayout->addWidget(statusLabel);

  // 진행률 바 (처음에는 숨김)
  progressBar = new QProgressBar(this);
  progressBar->setStyleSheet(R"(
    QProgressBar {
      font-size: 30px;
      border: 2px solid #444;
      border-radius: 10px;
      text-align: center;
      background-color: #292929;
      height: 50px;
    }
    QProgressBar::chunk {
      background-color: #465BEA;
      border-radius: 8px;
    }
  )");
  progressBar->setMinimum(0);
  progressBar->setMaximum(100);
  progressBar->hide();
  mainLayout->addWidget(progressBar);

  // 모델 목록 (테이블)
  modelTableWidget = new QTableWidget(this);
  modelTableWidget->setColumnCount(3);
  modelTableWidget->setHorizontalHeaderLabels({tr("Model"), tr("Size"), tr("Date")});
  modelTableWidget->setSelectionBehavior(QAbstractItemView::SelectRows);
  modelTableWidget->setSelectionMode(QAbstractItemView::SingleSelection);
  modelTableWidget->setEditTriggers(QAbstractItemView::NoEditTriggers);
  modelTableWidget->setVerticalScrollMode(QAbstractItemView::ScrollPerPixel);  // 픽셀 단위 스크롤
  modelTableWidget->verticalHeader()->setVisible(false);
  modelTableWidget->verticalHeader()->setDefaultSectionSize(100);  // 행 높이 늘림
  modelTableWidget->horizontalHeader()->setStretchLastSection(true);
  modelTableWidget->horizontalHeader()->setSectionResizeMode(0, QHeaderView::Stretch);
  modelTableWidget->horizontalHeader()->setSectionResizeMode(1, QHeaderView::ResizeToContents);
  modelTableWidget->horizontalHeader()->setSectionResizeMode(2, QHeaderView::ResizeToContents);
  modelTableWidget->setSortingEnabled(true);
  modelTableWidget->setStyleSheet(R"(
    QTableWidget {
      font-size: 40px;
      background-color: #292929;
      border-radius: 15px;
      padding: 10px;
    }
    QTableWidget::item {
      padding: 15px;
    }
    QTableWidget::item:selected {
      background-color: #2C2CE2;
    }
    QTableWidget::item:hover {
      background-color: #3C3C3C;
    }
    QHeaderView::section {
      font-size: 35px;
      background-color: #393939;
      padding: 10px;
      border: none;
    }
  )");
  connect(modelTableWidget, &QTableWidget::cellClicked, this, &ModelManagerDialog::onModelClicked);

  // 터치 스크롤 설정 (스크롤과 선택 분리)
  QScroller::grabGesture(modelTableWidget->viewport(), QScroller::LeftMouseButtonGesture);
  QScroller *scroller = QScroller::scroller(modelTableWidget->viewport());
  QScrollerProperties props = scroller->scrollerProperties();
  props.setScrollMetric(QScrollerProperties::DecelerationFactor, 0.8);  // 감속 비율 (높을수록 빨리 멈춤)
  props.setScrollMetric(QScrollerProperties::MaximumVelocity, 0.15);   // 최대 속도 제한
  scroller->setScrollerProperties(props);

  mainLayout->addWidget(modelTableWidget, 1);

  // 버튼 레이아웃
  QHBoxLayout *buttonLayout = new QHBoxLayout();

  // 다운로드 버튼
  downloadBtn = new QPushButton(tr("Download"), this);
  downloadBtn->setStyleSheet(R"(
    QPushButton {
      font-size: 40px;
      padding: 20px 40px;
      background-color: #465BEA;
      border-radius: 15px;
    }
    QPushButton:pressed {
      background-color: #3049F4;
    }
    QPushButton:disabled {
      background-color: #2B2B2B;
    }
  )");
  downloadBtn->setEnabled(false);
  connect(downloadBtn, &QPushButton::clicked, this, &ModelManagerDialog::onDownloadClicked);
  buttonLayout->addWidget(downloadBtn);

  refreshBtn = new QPushButton(tr("Refresh"), this);
  refreshBtn->setStyleSheet(R"(
    QPushButton {
      font-size: 40px;
      padding: 20px 40px;
      background-color: #393939;
      border-radius: 15px;
    }
    QPushButton:pressed {
      background-color: #4C4C4C;
    }
  )");
  connect(refreshBtn, &QPushButton::clicked, this, &ModelManagerDialog::fetchModelList);
  buttonLayout->addWidget(refreshBtn);

  resetBtn = new QPushButton(tr("Reset to Default"), this);
  resetBtn->setStyleSheet(R"(
    QPushButton {
      font-size: 40px;
      padding: 20px 40px;
      background-color: #E22C2C;
      border-radius: 15px;
    }
    QPushButton:pressed {
      background-color: #FF3333;
    }
  )");
  connect(resetBtn, &QPushButton::clicked, this, &ModelManagerDialog::resetToDefaultModel);
  buttonLayout->addWidget(resetBtn);

  // 취소 버튼 (다운로드 중에만 표시)
  cancelBtn = new QPushButton(tr("Cancel"), this);
  cancelBtn->setStyleSheet(R"(
    QPushButton {
      font-size: 40px;
      padding: 20px 40px;
      background-color: #E22C2C;
      border-radius: 15px;
    }
    QPushButton:pressed {
      background-color: #FF3333;
    }
  )");
  connect(cancelBtn, &QPushButton::clicked, this, &ModelManagerDialog::cancelDownload);
  cancelBtn->hide();
  buttonLayout->addWidget(cancelBtn);

  buttonLayout->addStretch();

  QPushButton *closeBtn = new QPushButton(tr("Close"), this);
  closeBtn->setStyleSheet(R"(
    QPushButton {
      font-size: 40px;
      padding: 20px 40px;
      background-color: #393939;
      border-radius: 15px;
    }
    QPushButton:pressed {
      background-color: #4C4C4C;
    }
  )");
  connect(closeBtn, &QPushButton::clicked, this, &QDialog::accept);
  buttonLayout->addWidget(closeBtn);

  mainLayout->addLayout(buttonLayout);
}

void ModelManagerDialog::showCurrentModelInfo() {
  QString modelName = QString::fromStdString(Params().get("DrivingModelName")).trimmed();
  if (modelName.isEmpty()) {
    modelName = DEFAULT_MODEL_NAME;
  }
  bool hasCustomModel = hasValidCustomModel(MODELS_DIR);

  if (hasCustomModel && !modelName.isEmpty()) {
    qint64 size = calculateDirSize(MODELS_DIR);
    currentModelLabel->setText(tr("Current Model: %1 (%2)")
                                   .arg(modelName)
                                   .arg(formatSize(size)));
  } else {
    currentModelLabel->setText(tr("Current Model: Default (Built-in)"));
  }

  // 디스크 여유 공간 표시
  QStorageInfo storage("/data");
  if (storage.isValid()) {
    diskUsageLabel->setText(tr("Available Storage: %1").arg(formatSize(storage.bytesAvailable())));
  }
}

void ModelManagerDialog::fetchModelList() {
  statusLabel->setText(tr("Loading model list..."));
  modelTableWidget->setRowCount(0);
  models.clear();

  QNetworkRequest request{QUrl(MODELS_JSON_URL)};
  request.setAttribute(QNetworkRequest::RedirectPolicyAttribute, QNetworkRequest::NoLessSafeRedirectPolicy);
  QNetworkReply *reply = networkManager->get(request);

  connect(reply, &QNetworkReply::finished, this, [this, reply]() {
    onModelListReceived(reply);
    reply->deleteLater();
  });
}

void ModelManagerDialog::onModelListReceived(QNetworkReply *reply) {
  if (reply->error() != QNetworkReply::NoError) {
    statusLabel->setText(tr("Network error: %1").arg(reply->errorString()));
    return;
  }

  QByteArray data = reply->readAll();
  QJsonParseError parseError;
  QJsonDocument doc = QJsonDocument::fromJson(data, &parseError);

  if (parseError.error != QJsonParseError::NoError) {
    statusLabel->setText(tr("JSON parse error: %1").arg(parseError.errorString()));
    return;
  }

  // Manifest signature verification (Ed25519 over canonical JSON).
  if (!verifyManifestSignature(doc)) {
    statusLabel->setText(tr("Signature verification failed"));
    return;
  }

  parseModelList(doc);
  showModelList();
}

void ModelManagerDialog::parseModelList(const QJsonDocument &doc) {
  QJsonObject root = doc.object();
  QJsonArray modelsArray = root["models"].toArray();

  for (const QJsonValue &val : modelsArray) {
    QJsonObject obj = val.toObject();

    ModelInfo model;
    model.id = obj["id"].toString();
    model.name = obj["name"].toString();
    model.baseUrl = obj["base_url"].toString();
    model.addedAt = obj["added_at"].toString();
    model.minimumSelectorVersion = obj["minimum_selector_version"].toInt(1);

    // ID 및 URL 검증
    if (!isValidModelId(model.id) || !isValidModelUrl(model.baseUrl)) {
      qWarning() << "Invalid model id or url:" << model.id << model.baseUrl;
      continue;
    }

    // 버전 호환성 체크
    if (model.minimumSelectorVersion > MODEL_SELECTOR_VERSION) {
      qWarning() << "Model requires newer selector version:" << model.id;
      continue;
    }

    // 파일 정보 파싱
    QJsonObject filesObj = obj["files"].toObject();
    for (auto it = filesObj.begin(); it != filesObj.end(); ++it) {
      QString filename = it.key();
      if (!isValidFilename(filename)) {
        qWarning() << "Invalid filename:" << filename;
        continue;
      }

      QJsonObject fileInfo = it.value().toObject();
      FileInfo info;
      info.size = fileInfo["size"].toVariant().toLongLong();
      info.sha256 = fileInfo["sha256"].toString();
      model.files[filename] = info;
    }

    if (model.files.size() >= 2) {  // 최소 2개 ONNX 파일 필요
      models.append(model);
    }
  }
}

void ModelManagerDialog::showModelList() {
  modelTableWidget->setRowCount(0);

  if (models.isEmpty()) {
    statusLabel->setText(tr("No models available"));
    return;
  }

  // 현재 사용 중인 모델명 가져오기
  QString currentModelName = QString::fromStdString(Params().get("DrivingModelName")).trimmed();
  if (currentModelName.endsWith(" (Installing...)")) {
    currentModelName.chop(16);
  }
  if (currentModelName.isEmpty()) {
    currentModelName = DEFAULT_MODEL_NAME;
  }

  statusLabel->setText(tr("Select a model and tap Download"));

  int availableCount = 0;
  for (const ModelInfo &model : models) {
    // 현재 사용 중인 모델은 목록에서 제외
    bool isCurrentModel = (model.name.compare(currentModelName, Qt::CaseInsensitive) == 0) ||
                          (model.id.compare(currentModelName, Qt::CaseInsensitive) == 0);
    if (isCurrentModel) {
      continue;
    }

    qint64 totalSize = 0;
    for (const auto &file : model.files) {
      totalSize += file.size;
    }

    int row = modelTableWidget->rowCount();
    modelTableWidget->insertRow(row);

    // 모델 이름
    QTableWidgetItem *nameItem = new QTableWidgetItem(model.name);
    nameItem->setData(Qt::UserRole, model.id);
    modelTableWidget->setItem(row, 0, nameItem);

    // 파일 크기
    QTableWidgetItem *sizeItem = new QTableWidgetItem(formatSize(totalSize));
    sizeItem->setTextAlignment(Qt::AlignCenter);
    modelTableWidget->setItem(row, 1, sizeItem);

    // 추가된 날짜
    QTableWidgetItem *dateItem = new QTableWidgetItem(model.addedAt);
    dateItem->setTextAlignment(Qt::AlignCenter);
    modelTableWidget->setItem(row, 2, dateItem);

    availableCount++;
  }

  if (availableCount == 0) {
    statusLabel->setText(tr("No other models available"));
  } else {
    // 기본 정렬: 날짜 최신순
    modelTableWidget->sortItems(2, Qt::DescendingOrder);
  }
}

void ModelManagerDialog::onModelClicked(int row, int column) {
  Q_UNUSED(column);
  QTableWidgetItem *item = modelTableWidget->item(row, 0);
  if (!item) return;

  selectedModelId = item->data(Qt::UserRole).toString();
  downloadBtn->setEnabled(true);

  // 현재 사용 중인 모델명 가져오기
  QString currentModelName = QString::fromStdString(Params().get("DrivingModelName")).trimmed();
  if (currentModelName.endsWith(" (Installing...)")) {
    currentModelName.chop(16);
  }
  if (currentModelName.isEmpty()) {
    currentModelName = DEFAULT_MODEL_NAME;
  }

  // 선택된 모델 정보 표시
  for (const ModelInfo &model : models) {
    if (model.id == selectedModelId) {
      qint64 totalSize = 0;
      for (const auto &file : model.files) {
        totalSize += file.size;
      }

      // 현재 사용 중인 모델인지 확인 (대소문자 무시 비교)
      bool isCurrentModel = (model.name.compare(currentModelName, Qt::CaseInsensitive) == 0) ||
                            (model.id.compare(currentModelName, Qt::CaseInsensitive) == 0);
      if (isCurrentModel) {
        statusLabel->setText(tr("Selected: %1 (%2) - Currently in use")
                                 .arg(model.name).arg(formatSize(totalSize)));
        downloadBtn->setEnabled(false);
      } else {
        statusLabel->setText(tr("Selected: %1 (%2) - Tap Download to install")
                                 .arg(model.name).arg(formatSize(totalSize)));
      }
      break;
    }
  }
}

void ModelManagerDialog::onDownloadClicked() {
  if (selectedModelId.isEmpty()) return;

  // 선택된 모델 찾기
  for (const ModelInfo &model : models) {
    if (model.id == selectedModelId) {
      // 현재 사용 중인 모델인지 확인
      QString currentModelName = QString::fromStdString(Params().get("DrivingModelName")).trimmed();
      // "(Installing...)" 접미사 제거하여 비교
      if (currentModelName.endsWith(" (Installing...)")) {
        currentModelName.chop(16);  // " (Installing...)" 길이
      }
      if (currentModelName.isEmpty()) {
        currentModelName = DEFAULT_MODEL_NAME;
      }
      // 대소문자 무시 비교 (name 또는 id와 비교)
      bool isCurrentModel = (model.name.compare(currentModelName, Qt::CaseInsensitive) == 0) ||
                            (model.id.compare(currentModelName, Qt::CaseInsensitive) == 0);
      if (isCurrentModel) {
        statusLabel->setText(tr("This model is already installed and in use."));
        return;
      }
      downloadModel(model);
      break;
    }
  }
}

void ModelManagerDialog::downloadModel(const ModelInfo &model) {
  // 임시 디렉토리 정리 및 생성
  QDir(MODELS_TMP_DIR).removeRecursively();
  QDir().mkpath(MODELS_TMP_DIR);

  currentDownload = model;
  currentFileIndex = 0;
  currentTmpDir = MODELS_TMP_DIR;
  isDownloading = true;

  // UI 상태 변경
  modelTableWidget->setEnabled(false);
  downloadBtn->hide();
  refreshBtn->hide();
  resetBtn->hide();
  cancelBtn->show();
  progressBar->setValue(0);
  progressBar->show();
  statusLabel->setText(tr("Preparing download..."));

  // 첫 번째 파일 다운로드 시작
  downloadNextFile();
}

void ModelManagerDialog::downloadNextFile() {
  QStringList filenames = currentDownload.files.keys();

  if (currentFileIndex >= filenames.size()) {
    // 모든 파일 다운로드 완료
    finalizeDownload();
    return;
  }

  QString filename = filenames[currentFileIndex];
  QString url = currentDownload.baseUrl + "/" + filename;
  QString filepath = currentTmpDir + "/" + filename;

  statusLabel->setText(tr("Downloading %1...").arg(filename));

  QNetworkRequest request{QUrl(url)};
  request.setAttribute(QNetworkRequest::RedirectPolicyAttribute, QNetworkRequest::NoLessSafeRedirectPolicy);
  currentReply = networkManager->get(request);

  connect(currentReply, &QNetworkReply::downloadProgress, this, &ModelManagerDialog::onDownloadProgress);

  connect(currentReply, &QNetworkReply::finished, this, [this, filepath, filename]() {
    QNetworkReply *reply = currentReply;
    currentReply = nullptr;

    if (reply->error() == QNetworkReply::OperationCanceledError) {
      statusLabel->setText(tr("Download canceled"));
      QDir(currentTmpDir).removeRecursively();
      finishDownloadUI();
      reply->deleteLater();
      return;
    }

    if (reply->error() != QNetworkReply::NoError) {
      showError(tr("Download failed: %1").arg(reply->errorString()));
      QDir(currentTmpDir).removeRecursively();
      finishDownloadUI();
      reply->deleteLater();
      return;
    }

    // 파일 저장
    QFile file(filepath);
    if (!file.open(QIODevice::WriteOnly)) {
      showError(tr("Failed to save file: %1").arg(filepath));
      QDir(currentTmpDir).removeRecursively();
      finishDownloadUI();
      reply->deleteLater();
      return;
    }
    file.write(reply->readAll());
    file.close();

    // 파일 검증
    FileInfo expectedInfo = currentDownload.files[filename];
    if (!verifyDownloadedFile(filepath, expectedInfo.size, expectedInfo.sha256)) {
      showError(tr("File verification failed: %1").arg(filename));
      QDir(currentTmpDir).removeRecursively();
      finishDownloadUI();
      reply->deleteLater();
      return;
    }

    reply->deleteLater();

    // 다음 파일 다운로드
    currentFileIndex++;
    downloadNextFile();
  });
}

void ModelManagerDialog::cancelDownload() {
  if (currentReply) {
    currentReply->abort();
  }
  isDownloading = false;

  // 다운로드 취소 시 tmp 폴더 정리
  QDir(MODELS_TMP_DIR).removeRecursively();
}

void ModelManagerDialog::finishDownloadUI() {
  isDownloading = false;
  selectedModelId.clear();
  modelTableWidget->setEnabled(true);
  downloadBtn->setEnabled(false);
  downloadBtn->show();
  refreshBtn->show();
  resetBtn->show();
  cancelBtn->hide();
  progressBar->hide();
}

void ModelManagerDialog::onDownloadProgress(qint64 received, qint64 total) {
  if (total > 0 && progressBar) {
    int percent = static_cast<int>((received * 100) / total);
    progressBar->setValue(percent);
  }
}

void ModelManagerDialog::onDownloadFinished() {
  // Handled in downloadNextFile lambda
}

void ModelManagerDialog::finalizeDownload() {
  // 다운로드 완료 - 재부팅 시 컴파일 예약
  finishDownloadUI();

  // PendingModelName 파라미터에 모델명 저장 (재부팅 시 manager.py가 컴파일)
  Params params;
  params.put("PendingModelName", currentDownload.name.toStdString());
  // DrivingModelName도 즉시 설정 (UI 표시용, 컴파일 완료 전에도 모델명 확인 가능)
  params.put("DrivingModelName", currentDownload.name.toStdString() + " (Installing...)");

  statusLabel->setText(tr("Download complete!\n\n"
                          "The model will be compiled automatically on next boot.\n"
                          "Rebooting device in 5 seconds..."));

  // 5초 후 자동 재부팅
  QTimer::singleShot(5000, this, []() {
    Hardware::reboot();
  });
}

void ModelManagerDialog::restartModeld() {
  // modeld 프로세스 종료 (manager가 자동 재시작)
  QProcess::execute("pkill", {"-f", "selfdrive.modeld.modeld"});
}

void ModelManagerDialog::resetToDefaultModel() {
  // 모든 모델 관련 폴더 및 파라미터 정리
  QDir(MODELS_DIR).removeRecursively();
  QDir(MODELS_TMP_DIR).removeRecursively();
  Params().remove("DrivingModelName");
  Params().remove("PendingModelName");

  showCurrentModelInfo();
  statusLabel->setText(tr("Reset to default model.\n\n"
                          "Rebooting device in 5 seconds..."));

  // 5초 후 자동 재부팅
  QTimer::singleShot(5000, this, []() {
    Hardware::reboot();
  });
}

bool ModelManagerDialog::verifyManifestSignature(const QJsonDocument &doc) {
  QJsonObject obj = doc.object();
  QString keyId = obj.take("key_id").toString().trimmed();
  QString signatureB64 = obj.take("signature").toString().trimmed();
  if (keyId.isEmpty() || signatureB64.isEmpty()) {
    qWarning() << "Manifest missing key_id/signature";
    return false;
  }

  // key_id로 공개키 선택
  auto it = MODEL_SIGNING_KEYS.find(keyId.toStdString());
  if (it == MODEL_SIGNING_KEYS.end()) {
    qWarning() << "Unknown key_id:" << keyId;
    return false;
  }

  QString publicKeyB64 = QString::fromStdString(it->second);

  // Canonical JSON 생성
  QByteArray canonical = toCanonicalJson(QJsonValue(obj));
  if (canonical.isEmpty()) {
    qWarning() << "Failed to build canonical JSON";
    return false;
  }

  // Base64 decode
  QByteArray publicKeyBytes = QByteArray::fromBase64(publicKeyB64.toLatin1());
  QByteArray signatureBytes = QByteArray::fromBase64(signatureB64.toLatin1());

  auto publicKey = parseEd25519PublicKey(publicKeyBytes);
  if (!publicKey) {
    qWarning() << "Invalid Ed25519 public key format/size for key_id:" << keyId;
    return false;
  }

  if (signatureBytes.size() != ED25519_SIGNATURE_LEN) {
    qWarning() << "Invalid signature length:" << signatureBytes.size();
    return false;
  }

  const bool ok = verifyEd25519Signature(canonical, signatureBytes, publicKey.get());
  if (!ok) qWarning() << "Manifest signature verification failed";
  return ok;
}

QByteArray ModelManagerDialog::toCanonicalJson(const QJsonValue &value) {
  if (value.isObject()) {
    QJsonObject obj = value.toObject();
    QStringList keys = obj.keys();
    std::sort(keys.begin(), keys.end());  // Unicode codepoint order

    QByteArray result = "{";
    bool first = true;
    for (const QString &key : keys) {
      if (!first) result += ",";
      first = false;

      // 키 직렬화
      result += jsonDumpsString(key) + ":";
      // 값 재귀 직렬화
      const QByteArray valueBytes = toCanonicalJson(obj[key]);
      if (valueBytes.isEmpty()) return {};
      result += valueBytes;
    }
    result += "}";
    return result;
  } else if (value.isArray()) {
    QJsonArray arr = value.toArray();
    QByteArray result = "[";
    bool first = true;
    for (const QJsonValue &v : arr) {
      if (!first) result += ",";
      first = false;
      const QByteArray valueBytes = toCanonicalJson(v);
      if (valueBytes.isEmpty()) return {};
      result += valueBytes;
    }
    result += "]";
    return result;
  } else if (value.isString()) {
    return jsonDumpsString(value.toString());
  } else if (value.isDouble()) {
    const double d = value.toDouble();
    if (!std::isfinite(d)) return {};
    double intpart = 0.0;
    if (std::modf(d, &intpart) != 0.0) return {};
    if (d < static_cast<double>(std::numeric_limits<qint64>::min()) ||
        d > static_cast<double>(std::numeric_limits<qint64>::max())) {
      return {};
    }
    return QByteArray::number(static_cast<qint64>(d));
  } else if (value.isBool()) {
    return value.toBool() ? "true" : "false";
  } else if (value.isNull()) {
    return "null";
  }
  return {};
}

bool ModelManagerDialog::verifyDownloadedFile(const QString &filepath, qint64 expectedSize, const QString &expectedHash) {
  QFile file(filepath);
  if (!file.open(QIODevice::ReadOnly)) {
    qWarning() << "Cannot open file for verification:" << filepath;
    return false;
  }

  // 1. 파일 크기 검증
  qint64 actualSize = file.size();
  if (actualSize != expectedSize) {
    qWarning() << "Size mismatch!" << filepath;
    qWarning() << "Expected:" << expectedSize << "Actual:" << actualSize;
    file.close();
    return false;
  }

  // 2. SHA256 해시 검증
  QCryptographicHash hash(QCryptographicHash::Sha256);
  if (!hash.addData(&file)) {
    qWarning() << "Failed to read file for hashing:" << filepath;
    file.close();
    return false;
  }

  QString actualHash = hash.result().toHex();
  file.close();

  if (actualHash.toLower() != expectedHash.toLower()) {
    qWarning() << "Hash mismatch!" << filepath;
    qWarning() << "Expected:" << expectedHash;
    qWarning() << "Actual:" << actualHash;
    return false;
  }

  return true;
}

bool ModelManagerDialog::isValidModelUrl(const QString &url) {
  return url.startsWith("https://raw.githubusercontent.com/happymaj11r/openpilot-models/");
}

bool ModelManagerDialog::isValidModelId(const QString &id) {
  // 허용: 영문, 숫자, 밑줄, 하이픈, 공백
  static QRegularExpression validPattern("^[a-zA-Z0-9_ -]+$");
  if (!validPattern.match(id).hasMatch()) return false;

  // 경로 탈출 차단
  if (id.contains("..") || id.contains("/") || id.contains("\\")) return false;

  // 예약어 차단
  if (id == "." || id == ".." || id.startsWith(".tmp_")) return false;

  return true;
}

bool ModelManagerDialog::isValidFilename(const QString &filename) {
  // 허용된 파일명만 (allowlist) - ONNX 파일
  static QStringList allowedFiles = {
      "driving_policy.onnx",
      "driving_vision.onnx"
  };
  return allowedFiles.contains(filename);
}

void ModelManagerDialog::showError(const QString &message) {
  statusLabel->setText(tr("Error: %1").arg(message));
  statusLabel->setStyleSheet("font-size: 35px; color: #E22C2C;");
  // 5초 후 원래 색상으로 복구
  QTimer::singleShot(5000, this, [this]() {
    statusLabel->setStyleSheet("font-size: 35px;");
  });
}

QString ModelManagerDialog::formatSize(qint64 bytes) {
  if (bytes < 1024) return QString::number(bytes) + " B";
  if (bytes < 1024 * 1024) return QString::number(bytes / 1024.0, 'f', 1) + " KB";
  if (bytes < 1024 * 1024 * 1024) return QString::number(bytes / (1024.0 * 1024.0), 'f', 1) + " MB";
  return QString::number(bytes / (1024.0 * 1024.0 * 1024.0), 'f', 2) + " GB";
}

qint64 ModelManagerDialog::calculateDirSize(const QString &path) {
  qint64 size = 0;
  QDir dir(path);
  for (const QFileInfo &info : dir.entryInfoList(QDir::Files | QDir::NoDotAndDotDot)) {
    size += info.size();
  }
  return size;
}
