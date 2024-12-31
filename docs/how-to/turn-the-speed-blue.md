# 将速度显示变成蓝色
*openpilot开发入门指南*

在30分钟内,我们将在你的电脑上搭建openpilot开发环境,并对openpilot的UI进行一些修改。

如果你有comma 3/3X设备,我们还将把修改部署到你的设备上进行测试。

## 1. 搭建开发环境

运行以下命令克隆openpilot并安装所有依赖:
```bash
bash <(curl -fsSL openpilot.comma.ai)
```

进入openpilot文件夹并激活Python虚拟环境
```bash
cd openpilot
source .venv/bin/activate
```

然后,编译openpilot:
```bash
scons -j8
```

## 2. 运行回放

我们将使用演示路线运行`replay`工具,获取数据流来测试我们的UI修改。
```bash
# in terminal 1
tools/replay/replay --demo

# in terminal 2
selfdrive/ui/ui
```

openpilot的UI应该会启动并显示演示路线的回放。

如果你有自己的comma设备,可以用你在comma connect上的路线替换`--demo`参数。

## 3. 将速度显示变成蓝色

在`ui`文件夹中使用git grep搜索"mph"。
```bash
$ git grep "mph" selfdrive/ui/
paint.cc:  ui_draw_text(s, s->fb_w/2, 290, s->scene.is_metric ? "km/h" : "mph", 36 * 2.5, COLOR_WHITE_ALPHA(200), "sans-regular");
```

上面那行包含实际的速度显示。虽然没有定义COLOR_BLUE,但通过git grep搜索COLOR_WHITE可以看到它是nvgRGBA(255, 255, 255, 255)。个人来说,我更喜欢浅蓝色,所以选择了#8080FF。
```bash
$ git diff
diff --git a/selfdrive/ui/paint.cc b/selfdrive/ui/paint.cc
index 821d95115..cc996eaa1 100644
--- a/selfdrive/ui/paint.cc
+++ b/selfdrive/ui/paint.cc
@@ -175,8 +175,8 @@ static void ui_draw_vision_speed(UIState *s) {
   const float speed = std::max(0.0, (*s->sm)["carState"].getCarState().getVEgo() * (s->scene.is_metric ? 3.6 : 2.2369363));
   const std::string speed_str = std::to_string((int)std::nearbyint(speed));
   nvgTextAlign(s->vg, NVG_ALIGN_CENTER | NVG_ALIGN_BASELINE);
-  ui_draw_text(s, s->fb_w/2, 210, speed_str.c_str(), 96 * 2.5, COLOR_WHITE, "sans-bold");
-  ui_draw_text(s, s->fb_w/2, 290, s->scene.is_metric ? "km/h" : "mph", 36 * 2.5, COLOR_WHITE_ALPHA(200), "sans-regular");
+  ui_draw_text(s, s->fb_w/2, 210, speed_str.c_str(), 96 * 2.5, nvgRGBA(128, 128, 255, 255), "sans-bold");
+  ui_draw_text(s, s->fb_w/2, 290, s->scene.is_metric ? "km/h" : "mph", 36 * 2.5, nvgRGBA(128, 128, 255, 200), "sans-regular");
 }

 static void ui_draw_vision_event(UIState *s) {
```


## 4. 重新构建UI,欣赏你的作品

```bash
scons -j8 && selfdrive/ui/ui
```

![](https://blog.comma.ai/img/blue_speed_ui.png)

## 5. 将你的分支推送到GitHub

在GitHub上点击fork。然后使用以下命令推送:
```bash
git remote rm origin
git remote add origin git@github.com:<your-github-username>/openpilot.git
git add .
git commit -m "Make the speed blue."
git push --set-upstream origin master
```

## 6. 在你的车上运行你的分支!

通过设置卸载设备上的openpilot。然后输入你自己的安装程序URL:
```
installer.comma.ai/<your-github-username>/master
```

## 7. 在现实中欣赏你的作品

![](https://blog.comma.ai/img/c3_blue_ui.jpg)
