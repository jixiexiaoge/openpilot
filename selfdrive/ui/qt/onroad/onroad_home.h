#pragma once

#include "selfdrive/ui/qt/onroad/alerts.h"
#include "selfdrive/ui/qt/onroad/annotated_camera.h"

class OnroadWindow : public QWidget {
  Q_OBJECT

public:
  OnroadWindow(QWidget* parent = 0);
  bool isMapVisible() const { return map && map->isVisible(); }
  void showMapPanel(bool show) { if (map) map->setVisible(show); }

signals:
  void mapPanelRequested();

private:
  void createMapWidget();
  void paintEvent(QPaintEvent *event);
  void mousePressEvent(QMouseEvent* e) override;
  OnroadAlerts *alerts;
  AnnotatedCameraWidget *nvg;
  QColor bg = bg_colors[STATUS_DISENGAGED];
  QWidget *map = nullptr;
  QHBoxLayout* split;

  // FrogPilot variables
  Params params;
  Params params_memory{"/dev/shm/params"};

  inline QColor redColor(int alpha = 255) { return QColor(201, 34, 49, alpha); }

  QPoint timeoutPoint = QPoint(420, 69);

  QTimer clickTimer;

  bool blindSpotLeft;
  bool blindSpotRight;
  bool hasLead;
  bool liveValid;
  bool showBlindspot;
  bool showFPS;
  bool showJerk;
  bool showSignal;
  bool showSteering;
  bool showTuning;
  bool turnSignalLeft;
  bool turnSignalRight;

  float currentAcceleration;
  float fps;
  float friction;
  float latAccel;
  float steer;

  int accelerationJerk;
  int accelerationJerkDifference;
  int speedJerk;
  int speedJerkDifference;
  int steeringAngleDeg;

private slots:
  void offroadTransition(bool offroad);
  void primeChanged(bool prime);
  void updateState(const UIState &s);
};
