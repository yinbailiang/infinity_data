# 外部导入

> 本页属于 InfinityData 语言参考，章节编号沿用完整规范（§x.y）。

> **导入语句共同规则**：导入项之间必须用逗号分隔（不接受换行/空格分隔）；且整个
> 导入语句必须以**换行或文件末尾**结尾——同一行逗号后不能再接其他语句
> （见 §1.1「逗号换行等价（双向）」的导入例外，`!env` 与 `!file`/`!from` 同等适用）。

## 3.1 环境变量导入

> 环境变量导入不直接注入，需要使用 `$` 起始来在导入空间中找查目标

基础语法:
- `!env import NAME`
- `!env import NAME as NEW_NAME`
- `!env import NAME as NEW_NAME, name2, name3 as OTHER` （一次导入多个，逗号分隔）

使用:
- `user_name = $NAME` 默认为字符串
- `user_id = $USER_ID as int` 支持转换，bool | int | float | str

转换规则:
- `as bool`: `("true", "1") | ("false", "0") -> true | false` 不分大小写
- `as int`: `"NUMBER" -> NUMBER` 支持正负，不支持小数
- `as float`: `"NUMBER ->" NUMBER` 支持正负，科学计数，点起始
- **转换对所有导入空间通用**：`$name as type` 作用于**任何**导入空间的字符串数据
  （`!env` / `!file` 含 `raw` / `!var`），与来源无关——见 §1.8
- **空字面量保持传播**：`null` / `noexist` 经 `as` 转换**原样保持**（不转换、不警告、
  不回退）——见 §1.8

## 3.2 模板导入

基础语法:
- `!from p"Path to .inft file" import Template1, Template2`
- `!from p"Path to .inft file" import Template1 as T1`

Path规则:
- **导入路径必须用 `p"..."` 路径字面量**（§1.5）；普通字符串 → `parse.import_path_required` 错误（容错恢复）
- 路径分割符: unix 风格 `/`（语言内**只允许** POSIX 风格，不接受 `\`）
- 相对路径: 相对路径起始点为导入所在文件的位置
- 支持绝对路径
- Windows 盘符: 写作 `/c/XXX/xxx/x.inft`（小写单字母 = 盘符）
- **跨平台自动映射**: 同一份 .infd 在 linux/windows/mac 均可用——访问文件系统时
  编译器按当前平台把 `/c/...` 映射为 `C:\...`
- **Windows 无盘符绝对路径**: `/usr/local` 这类不带盘符的绝对路径在 Windows 上
  按**当前盘根**（base 所在盘）处理，如 `C:\usr\local`——与 Linux/mac 的「根」语义
  不同，这是平台差异而非错误；跨平台路径建议始终显式写盘符（`/c/...`）
- **strict 沙盒语义**：`strict=True`（默认）下，白名单**内**但目标不存在 → 抛 `sandbox.file_missing`
  （ERROR，中止编译并返回空文档）——`!file` / `!from` 是配置显式声明的依赖，缺失属于部署错误，
  不应退化成可用配置；`strict=False`（扫描 / 容错模式）仍按软失败处理：产出 `import.file_missing`
  警告、目标值退化为 noexist

> glob 白名单统一按语言内 POSIX 形式匹配
> 文件内存在的模板定义不能和导入的模板冲突。否则是错误
> **文件级循环导入**：递归加载中，已加载文件的本地模板名**先注册可见**；再次遇到
> 同一文件 → 复用已构建 scope（不重复解析）——互导可安全终止，不无限递归
> **导入递归深度上限**：实现须防止深链递归耗尽资源（当前实现：上限 32 层，
> 超限报 `template.import_depth`）；模板**依赖**环的身份处理另见 §2.5「环处理」
> **.inft 允许导入语句**：模板定义文件除 `!from` 外，还允许 `!env` / `!file` / `!var`
> （数据导入，绑定**该文件**自己的 `$` 命名空间，就地解析——§1.8）；不允许数据字段与结构级约束
> （`inft.not_allowed` 仅对字段/约束保留）。相对路径（`!file`）按 **.inft 文件所在目录**解析
> （与 `!from` 一致）。

使用:
- 同正常模板
- 无需 $ 前缀

## 3.3 现有配置导入

> 配置导入不直接注入，需要使用 `$` 起始来在导入空间中找查目标

基础语法:
- `!file p"Path to config file" as yaml import .a.b.c as c`
- `!file p"Path to config file" as yaml import . as a, .c as c`

Path规则同模板导入（**必须用 `p"..."` 路径字面量**）

导入规则:
- `as`: 可写可不写，不写默认看文件后缀，支持yaml，json，toml，raw(直接导入字符串)
- **`raw`（直接导入字符串）**: 不做任何解析，文件**原文**整体作为字符串值导入
  （`import . as name` 绑定整个文件内容）；路径投影作用于字符串时无意义，
  `.` 以外的 path 段 → `import.path_failed` 警告。默认后缀映射
  `.txt` / `.text` / `.md` / `.log` → `raw`：
  ```infd
  !file p"README.md" import . as readme     # 等价于 as raw
  !file p"seed.txt" as raw import . as seed # 显式声明

  content = $readme    # 字符串，保留原文（含换行等）
  ```
- `import`: 必须 `.path.to."target/?".data as name` 支持数组下标，比如
```json
{
  "a":{
    "b":[
      {
        "c":1
      }
    ]
  }
}
```
想要其中的c
```infd
!file p"example.json" as json import .a.b[0]."c" as c
```
起始的`.`表示从文件根开始寻址

使用:
```infd
!file p"example.json" as json import .a.b[0]."c" as c, .a.b as b

example_c = $c
example_list: <list, each(dict)> = $b

!file p"example.json" as json import . as example

all_data = $example
```
