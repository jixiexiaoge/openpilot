# 连接到comma 3/3X设备

comma 3/3X是一台普通的[Linux](https://github.com/commaai/agnos-builder)计算机,提供[SSH](https://wiki.archlinux.org/title/Secure_Shell)和[串口控制台](https://wiki.archlinux.org/title/Working_with_the_serial_console)访问。

## 串口控制台

在comma three和3X设备上,串口控制台都可以通过主OBD-C端口访问。
使用普通USB C数据线将comma 3/3X连接到电脑,或使用[comma串口线](https://comma.ai/shop/comma-serial)获得稳定的12V供电。

在comma three上,串口控制台通过UART-to-USB芯片提供,可以使用`tools/scripts/serial.sh`脚本连接。

在comma 3X上,可以通过[panda](https://github.com/commaai/panda)使用`panda/tests/som_debug.sh`脚本访问串口控制台。

  * Username: `comma`
  * Password: `comma`

## SSH

要通过SSH连接到设备,你需要一个配置了SSH密钥的GitHub账户。参见这篇[GitHub文章](https://docs.github.com/en/github/authenticating-to-github/connecting-to-github-with-ssh)了解如何为账户设置SSH密钥。

* 在设备设置中启用SSH
* 在设备设置中输入你的GitHub用户名
* 连接到你的设备
    * 用户名: `comma`
    * 端口: `22`

这是一个使用网络共享连接到设备的示例命令:<br />
`ssh comma@192.168.43.1`

在设备上进行开发工作时,建议使用[SSH代理转发](https://docs.github.com/en/developers/overview/using-ssh-agent-forwarding)。

### Notes

公钥只会从你的GitHub账户获取一次。如果要更新设备的授权密钥,你需要重新输入GitHub用户名。

此目录中的`id_rsa`密钥仅在设备处于未安装软件的设置状态时有效。安装完成后,该默认密钥将被移除。

#### ssh.comma.ai代理

通过[comma prime订阅](https://comma.ai/connect),你可以从任何地方SSH连接到你的comma设备。

使用以下SSH配置,你可以输入`ssh comma-{dongleid}`通过`ssh.comma.ai`连接到你的设备。

```
Host comma-*
  Port 22
  User comma
  IdentityFile ~/.ssh/my_github_key
  ProxyCommand ssh %h@ssh.comma.ai -W %h:%p

Host ssh.comma.ai
  Hostname ssh.comma.ai
  Port 22
  IdentityFile ~/.ssh/my_github_key
```

### One-off connection

```
ssh -i ~/.ssh/my_github_key -o ProxyCommand="ssh -i ~/.ssh/my_github_key -W %h:%p -p %p %h@ssh.comma.ai" comma@ffffffffffffffff
```
(Replace `ffffffffffffffff` with your dongle_id)

### ssh.comma.ai host key fingerprint

```
Host key fingerprint is SHA256:X22GOmfjGb9J04IA2+egtdaJ7vW9Fbtmpz9/x8/W1X4
+---[RSA 4096]----+
|                 |
|                 |
|        .        |
|         +   o   |
|        S = + +..|
|         + @ = .=|
|        . B @ ++=|
|         o * B XE|
|         .o o OB/|
+----[SHA256]-----+
```
