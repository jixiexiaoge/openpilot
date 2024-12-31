# openpilot文档

这是[docs.comma.ai](https://docs.comma.ai)的源代码。
网站通过这个[工作流](../.github/workflows/docs.yaml)在master分支更新时自动更新。

## 开发说明
注意:以下命令必须在openpilot的根目录下运行,**而不是在/docs目录下**

**1. 安装文档依赖**
``` bash
pip install .[docs]
```

**2. 构建新站点**
``` bash
mkdocs build
```

**3. 本地运行新站点**
``` bash
mkdocs serve
```

参考资料:
* https://www.mkdocs.org/getting-started/
* https://github.com/ntno/mkdocs-terminal
