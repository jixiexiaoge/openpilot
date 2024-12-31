{% set footnote_tag = '[<sup>{}</sup>](#footnotes)' %}
{% set star_icon = '[![star](assets/icon-star-{}.svg)](##)' %}
{% set video_icon = '<a href="{}" target="_blank"><img height="18px" src="assets/icon-youtube.svg"></img></a>' %}
{# 通过使用带最大宽度的空白图片强制硬件列更宽 #}
{% set width_tag = '<a href="##"><img width=2000></a>%s<br>&nbsp;' %}
{% set hardware_col_name = '所需硬件' %}
{% set wide_hardware_col_name = width_tag|format(hardware_col_name) -%}

<!--- 本文件由 selfdrive/car/CARS_template.md 自动生成,请勿直接编辑 --->

# 支持的车型

支持的车型指的是安装comma设备后可以直接使用的车型。所有支持的车型都能提供比原厂系统更好的体验。除非特别说明,所有支持的车型均指美国市场版本。

# 目前支持 {{all_car_docs | length}} 种车型

|{{Column | map(attribute='value') | join('|') | replace(hardware_col_name, wide_hardware_col_name)}}|
|---|---|---|{% for _ in range((Column | length) - 3) %}{{':---:|'}}{% endfor +%}
{% for car_docs in all_car_docs %}
|{% for column in Column %}{{car_docs.get_column(column, star_icon, video_icon, footnote_tag)}}|{% endfor %}

{% endfor %}

### 注释说明
{% for footnote in footnotes %}
<sup>{{loop.index}}</sup>{{footnote}} <br />
{% endfor %}

## 社区维护的车型
虽然这些车型没有被官方支持,但社区成员已经在其他品牌和型号上运行了openpilot。您可以在[我们的wiki](https://wiki.comma.ai/)上查看每个品牌的"社区支持型号"部分。

# 没有找到您的车型?

**openpilot 可以支持比目前更多的车型。** 您的车型未被支持可能有以下几个原因。
如果您的车辆不符合这里列出的任何不兼容标准,那么很可能可以被支持!我们一直在增加对新车型的支持。**我们没有车型支持的路线图**,事实上,大多数车型支持都来自像您这样的用户!

### 哪些车型可以被支持?

openpilot 使用您车辆中现有的转向、油门和制动接口。如果您的车辆缺少其中任何一个接口,openpilot 将无法控制车辆。如果您的车辆具有[自适应巡航控制(ACC)](https://en.wikipedia.org/wiki/Adaptive_cruise_control)和任何形式的[车道保持辅助系统(LKAS)](https://en.wikipedia.org/wiki/Automated_Lane_Keeping_Systems)/[车道居中辅助(LCA)](https://en.wikipedia.org/wiki/Lane_centering),那么它几乎肯定具有这些接口。这些功能通常从2016年左右开始在车辆上配备。请注意,制造商通常会为这些功能使用自己的[营销术语](https://en.wikipedia.org/wiki/Adaptive_cruise_control#Vehicle_models_supporting_adaptive_cruise_control),例如现代的"智能巡航控制"就是自适应巡航控制的品牌名称。

如果您的车辆具有以下套件或功能,那么它就是支持的好候选者:

| 品牌 | 所需套件/功能 |
| ---- | ------------ |
| 讴歌 | 任何带有AcuraWatch Plus的车型都可以使用。许多新款车型都标配AcuraWatch Plus。 |
| 福特 | 任何带有车道居中功能的车型都可能可以使用。 |
| 本田 | 任何带有Honda Sensing的车型都可以使用。许多新款车型都标配Honda Sensing。 |
| 斯巴鲁 | 任何带有EyeSight的车型都可以使用。许多新款车型都标配EyeSight。 |
| 日产 | 任何带有ProPILOT的车型都可能可以使用。 |
| 丰田和雷克萨斯 | 任何带有丰田/雷克萨斯Safety Sense系统,并具有"带转向辅助的车道偏离警告(LDA w/SA)"和/或"车道追踪辅助(LTA)"的车型都可以使用。注意:不带转向辅助的LDA将无法使用。这些功能在大多数新款车型上都是标配。 |
| 现代、起亚和捷尼赛思 | 任何带有智能巡航控制(SCC)和车道跟随辅助(LFA)或车道保持辅助(LKAS)的车型都可以使用。LKAS/LFA在大多数新款车型上都是标配。任何形式的SCC都可以使用,如NSCC。 |
| 克莱斯勒、Jeep和Ram | 任何带有LaneSense和自适应巡航控制的车型都可能可以使用。这些在许多新款车型上都是标配。 |

### FlexRay系统

openpilot支持的所有车型都使用[CAN总线](https://en.wikipedia.org/wiki/CAN_bus)在车辆的所有计算机之间进行通信,但CAN总线并不是车辆计算机通信的唯一方式。以下制造商的大多数(如果不是全部)车辆使用[FlexRay](https://en.wikipedia.org/wiki/FlexRay)而不是CAN总线:**宝马、奔驰、奥迪、路虎和部分沃尔沃**。这些车型可能有一天会得到支持,但我们目前没有支持FlexRay的即时计划。

### 丰田安全系统

由于采用了新的消息认证方法,openpilot目前尚不支持以下丰田车型。
如果您希望看到这些车型得到openpilot支持,请在[这里投票](https://comma.ai/shop#toyota-security)。

* 丰田 RAV4 Prime 2021+
* 丰田 Sienna 2021+
* 丰田 Venza 2021+
* 丰田 Sequoia 2023+
* 丰田 Tundra 2022+
* 丰田 Highlander 2024+
* 丰田 Corolla Cross 2022+ (仅限美版)
* 丰田 Camry 2025+
* 雷克萨斯 NX 2022+
* 丰田 bZ4x 2023+
* 斯巴鲁 Solterra 2023+ 