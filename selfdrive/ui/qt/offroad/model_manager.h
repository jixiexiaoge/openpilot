#pragma once

#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QProgressBar>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>
#include <QMap>
#include <QLabel>
#include <QVBoxLayout>
#include <QPushButton>
#include <QTableWidget>
#include <QHeaderView>

#include "selfdrive/ui/qt/widgets/input.h"

// 기본 내장 모델명 (변경 시 이 상수만 수정)
const QString DEFAULT_MODEL_NAME = "DTRv6";

struct FileInfo {
  qint64 size;
  QString sha256;
};

class ModelInfo {
public:
  QString id;           // 모델 ID (폴더명, 버전 포함: wmi, wmiv2)
  QString name;         // 표시 이름
  QString baseUrl;      // 다운로드 URL
  QString addedAt;      // 추가된 날짜
  QMap<QString, FileInfo> files;  // filename → {size, sha256} (ONNX 파일)
  int minimumSelectorVersion;     // 최소 셀렉터 버전
};

// 현재 모델 상태
enum class ModelStatus {
  Default,      // 기본 내장 모델 사용 중
  Custom,       // 커스텀 모델 사용 중
  Downloading,  // 다운로드 중
  Compiling,    // 컴파일 중
};

class ModelManagerDialog : public DialogBase {
  Q_OBJECT

public:
  explicit ModelManagerDialog(QWidget *parent);

private slots:
  void fetchModelList();
  void onModelListReceived(QNetworkReply *reply);
  void onModelClicked(int row, int column);
  void onDownloadClicked();
  void downloadModel(const ModelInfo &model);
  void downloadNextFile();
  void onDownloadProgress(qint64 received, qint64 total);
  void onDownloadFinished();
  void finalizeDownload();
  void resetToDefaultModel();
  void cancelDownload();

private:
  QNetworkAccessManager *networkManager;
  QNetworkReply *currentReply;
  QString selectedModelId;
  QList<ModelInfo> models;
  ModelInfo currentDownload;
  int currentFileIndex;
  QString currentTmpDir;
  bool isDownloading;

  // UI Elements
  QVBoxLayout *mainLayout;
  QLabel *statusLabel;
  QLabel *currentModelLabel;
  QLabel *diskUsageLabel;
  QProgressBar *progressBar;
  QTableWidget *modelTableWidget;
  QPushButton *downloadBtn;
  QPushButton *refreshBtn;
  QPushButton *resetBtn;
  QPushButton *cancelBtn;

  void setupUI();
  void parseModelList(const QJsonDocument &doc);
  void showModelList();
  void showCurrentModelInfo();
  void finishDownloadUI();
  bool verifyManifestSignature(const QJsonDocument &doc);
  bool verifyDownloadedFile(const QString &filepath, qint64 expectedSize, const QString &expectedHash);
  void restartModeld();
  void showError(const QString &message);
  QString formatSize(qint64 bytes);
  qint64 calculateDirSize(const QString &path);

  // Canonical JSON for signature verification
  QByteArray toCanonicalJson(const QJsonValue &value);

  // URL validation
  bool isValidModelUrl(const QString &url);
  bool isValidModelId(const QString &id);
  bool isValidFilename(const QString &filename);
};
