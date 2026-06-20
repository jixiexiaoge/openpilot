# IQ.Pilot:



## Join Our Public Beta at: https://discord.iqlvbs.com

## Running IQ.Pilot
* A modern comma, or clone device to run this software (Comma 3, 3x, 4, Konik A1/M, Mr.One C3, C3 Lite)
* One of [the supported cars](https://gitlvb.teallvbs.xyz/IQ.Lvbs/IQ.Pilot/src/branch/release/opendbc_repo/docs/CARS.md).
* A [car harness](https://comma.ai/shop/products/car-harness) to connect to your car
#### Side Note: Volkswagen Group, and Tesla vehicles are currently the most compatible for use with IQ.Pilot, other manufacturers are supported at a minimum to the same level as stock openpilot, but are not a top priority while we are in beta.
## Installation
#### Installing Via Installer URL:
#### Enter the following into your device custom URL box to install IQ.Pilot:
`IQLvbs/release`
#### Having Trouble? If your device is currently running AGNOS 13.1 or older, you should install latest stock openpilot, then install IQ.Pilot, or try one of the alternative methods listed below!


## Alternative Methods of Installation:
#### Enabling SSH:
* In your device's settings, go into "Developer Settings"
* Enable the "Enable SSH" toggle if it is not already on.
* Next to "SSH Keys", click on "Add" and then enter your GitHub username.
* Run the command below (replace your_email@example.com with your GitHub account email, then paste the output [here](https://github.com/settings/keys) after clicking on "New SSH Key", then reboot your comma device.
#### SSH Key Command: `ssh-keygen -t ed25519 -C "your_email@example.com" -f ~/.ssh/id_ed25519 -N "" && cat ~/.ssh/id_ed25519.pub`
#### Note: If you have already setup SSH and can SSH into your device, skip this section.

#### Installing Via SSH:
#### Once you are connected to your device via SSH, you can paste the following command below to install IQ.Pilot:
`cd .. && rm -rf openpilot && git clone https://github.com/IQLvbs/openpilot.git -b release && cd openpilot && sudo reboot`
#### If you'd like to backup your previous installation as well, paste the following command below to install IQ.Pilot:
`cd .. && mv openpilot openpilot_backup_X && git clone https://github.com/IQLvbs/openpilot.git -b release && cd openpilot && sudo reboot`
#### Alternatively, you can use your existing fork's built in tools to switch your branch as well:
`git remote add iqpilot https://github.com/IQLvbs/openpilot.git && op switch iqpilot release`

## Releases:
#### IQ.Pilot's Beta Is Currently At Release 1.0c
|  Version  |          Installation URL           |
|:---------:|:-----------------------------------:|
| `release` | `installer.comma.ai/IQLvbs/release` |
|  `beta`   |  `installer.comma.ai/IQLvbs/beta`   |
#### Side Note: Beta's are releases of IQ.Pilot that are released publically for beta testing by the IQ.Pilot team, expect bugs, and unstable behavior, for stability please use release.

## 📊 User Data
### IQ.Pilot uploads your data to Konn3kt, by IQ.Lvbs.
#### Konn3kt is the most secure, encrypted, feature rich management platform for your IQ.Pilot device. Konn3kt has dual end-to-end encryption, your data is encrypted in transit, and at rest, you, and only you have access to your device, and your data.

#### IQ.Pilot allows users to disable uploading entirely if they wish.
#### Konn3kt doesn't collect driver camera, microphone data (if disabled in IQ.Pilot) and parses your logs, and video data with dual end-to-end encryption, ensuring that your data is accessible to you, and only you, not even accessible to IQ.Lvbs.

## Terms of Service / Privacy Policy / Licensing
#### IQ.Pilot is subject to the License found in this repository, [Terms of Service](https://konn3kt.com/tos), and, [Privacy Policy](https://konn3kt.com/privacy).


## Support IQ.Pilot?
Sorry, I have better things to do than ask my users for donations. - Teal

<span>-</span> IQ.Lvbs, by Project Teal Lvbs
