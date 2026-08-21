# InfinityData Language 设计文档

## 0. 基础设定

### 0.1 编码

本语言唯一合法的编码为 utf-8 NO BOM LF

### 0.2 文件类型

采用如下两种后缀名:
- .infd 允许模板定义和数据定义
- .inft 仅允许模板定义

### 0.3 顶层数据模型

顶层所有非模板定义共同构成一个 dict

## 1. 基础语法

### 1.1 字段定义

基础语法:
- 简单键值对 `name = default,`

复合值语法:
- `a_list = [a, b, c]` 元素之间以逗号或换行分隔
- `a_dict = {a = 1, b = 2}` 键值对之间以逗号或换行分隔
- 尾值后的逗号可选：`[a, b, c,]` / `{a = 1, b = 2,}` 均合法

特殊规则:
- **显式分隔符**：容器内元素之间**必须显式分隔**——逗号或换行，二者等价；
  **空格不构成分隔符**（`[1 2]` 报缺少分隔符错误）
- **省略等号**：仅限复合值与模板调用——`server { ... }` / `server [ ... ]` / `server Server(...)`；
  字面量与 `$` 引用必须显式写等号（`x = 123`；`x 123` 报缺少等号错误）
- **逗号换行等价（双向）**：除导入语法（`!from "a" import X, Y` 必须用逗号和尾最后换行）外，
  任何需要逗号/换行的地方都可用另一方替代——顶层同样接受逗号分隔，
  整个文件（含模板定义、字段、结构级约束）可压缩成一行：
  `a = 1, b = [1, 2], ~T { x: int = 1 }, c = T(x = 2),`

### 1.2 约束

#### 1.2.1 字段约束

基础语法:
- `key: constraint = default,`
- `key: <constraint, ...> = default,`

约束列表与约束参数同样以逗号或换行分隔（`<int\nrange(1, 10)>` / `range(1,\n10)` 合法；
空格不构成分隔）

内置类型约束:
- `?` 值只能是 `null` 或者 `noexist`
- `object` 任何不是 `null` 或者 `noexist` 的值
- `int`, `str`, `bool`, `float`, `list`, `dict` 字面意思
- `object?`, `int?`, `str?`, `bool?`, ... 便携可空类型语法糖

内置一般约束:
- `range(ge, le)` 数值范围，ge/le 可省略一端
- `size(ge, le)` 集合大小或字符串长度
- `each(constraint)` list 每个元素均满足约束则满足，dict 每个键的值均满足则满足
- `in(choice, ...)` 值必须在给定选项中
- `ip`, `ip4`, `ip6` IP 地址格式
- `regex("re")` 正则匹配
- `email` 邮箱格式
- `url` URL 格式
- `uuid` UUID 格式
- `hostname` 主机名格式
- `positive` 正数 (> 0)
- `negative` 负数 (< 0)
- `nonnegative` 非负数 (>= 0)
- `eq(value)` 等于指定值
- `unique` 集合元素不重复

字典约束:
- `has(key)` dict 包含指定键则满足
- `field(name, constraint)` 对某个field进行约束，如果field不存在或者约束失败，则不满足

> **与三态可空的交互**：`noexist` 字段（键不出现）对 `has` / `field` 均视为**不存在**——
> `has(noexist字段)` 不满足、`field(noexist字段, c)` 视为字段缺失（不满足）。
> 由此「可选字段（默认 `noexist`）+ 结构级约束」可自然表达「至少声明其一」:
> ```infd
> ~ResourceSpec {
>     requests: <dict?> = noexist,
>     limits: <dict?> = noexist,
>     : <one(has(requests), has(limits))>,   # 至少提供其一；都没提供则违反
> }
> r = ResourceSpec(limits = {cpu = "1"})     # ✅ has(requests)=false, has(limits)=true
> ```

逻辑约束:
- `not(constraint)` 内部约束不满足则满足
- `any(constraint_a, constraint_b, ...)` 内部约束有任意多个被满足则满足
- `one(constraint_a, constraint_b, ...)` 内部约束只有一个被满足则满足
- `all(constraint_a, constraint_b, ...)` 内部约束全部满足则满足
- `when(condition, requirement)`         当condition满足时，要求requirement满足

特殊规则:
- **单约束可省略尖括号**: `field: int = 10` 等价于 `field: <int> = 10`
- **默认all**: <a, b, c> 等价 all(a, b, c)
- **可空约束**：`任意类型约束type_c`+`?` 等价 one(type_c, ?)

#### 1.2.2 结构级约束（dict 级约束）

> 以 `:` 起始，约束目标为所在 dict 的**整体**，而非某个字段。
> 可在任意 dict 构造位置使用；全局是隐式 dict，故顶层默认可用。

基础语法:
- `: <constraint, ...>`
- `: constraint` 单约束可省略尖括号

规则:
- `:` 可在以下位置使用：
  - 模板（`~Template { ... }`）内部 → 约束每次实例化出的整个 dict
  - 任意 dict 字面量（`{ ... }`）内部 → 约束该字面量 dict
  - 顶层（隐式 dict）→ 约束编译产物 root
- 约束目标是所在 dict 的整体，而非某个字段。
- 约束函数与字段级约束完全共用（同一注册表）。
- 约束中的模板名按**书写位置的可见性**（scope）解析。

模板内示例:
```infd
~Server {
    host: str?
    ip: str?
    port: <int, range(1, 65535)> = 80,
    tls: bool = false,
    debug: bool = false,
    mode: <str, in("production", "staging")> = "production",

    # 互斥字段：要么有 host 要么有 ip
    : <one(has(host), has(ip))>,

    # port=443 时必须启用 TLS
    : <when(field(port, eq(443)), field(tls, eq(true)))>,

    # debug 模式下端口必须大于 1024
    : <when(field(debug, eq(true)), field(port, range(1025, 65535)))>,

    # 生产环境必须启用 TLS
    : <when(field(mode, eq("production")), field(tls, eq(true)))>,
}

# 实例化：所有 : 约束在语义分析时校验
my_server = Server(port=443, tls=true)
# ✅ 通过

# 违反时获得明确的错误信息
bad_server = Server(port=443, tls=false)
# ❌ 约束违反: when(field(port, eq(443)), field(tls, eq(true)))
```

dict 字面量内示例（无需先定义模板）:
```infd
server {
    host = "node-1"
    port = 443
    : <one(has(host), has(ip))>
    : <when(field(port, eq(443)), field(tls, eq(true)))>
}
```

顶层示例（根级交叉校验，文件内自我声明）:
```infd
!env import MODE
mode = $MODE
tls = false

# 生产环境必须启用 TLS（作用于编译产物 root）
: <when(field(mode, eq("prod")), field(tls, eq(true)))>
```


### 1.3 注释

单行:
- 以 `#` 开始，直达该行结束

多行:
- 以 `#+` 开始，遇到 `#-` 结束
- `#` 可以有任意多个 `+` 或 任意多个 `-` 标记，但是开始和结束的标记数量必须相等
- 开始标记为 `#` + `+` * N 则结束标记为 `#` + `-` * N
- 多行注释外的未匹配的起始或结束token都是词法错误

### 1.4 基础类型

内置类型:
- `object` 所有类型都是object，除了 `?`
- `?` 纯可空类型，值可以是 noexist 或者 null
- `bool` 布尔值， true 或者 false
- `int` 有符号整数，无限精度
- `float` 无限精度10进制浮点
- `str` utf-8编码字符串，无尾0
- `list` 数组类型，内部元素可以是任何类型
- `dict` 字典类型，键名为utf-8无尾0字符串，值是 object

### 1.5 字面量

内置字面量:
- `true`
- `false`
- `null`
- `noexist`
- `nan`
- `+inf`, `-inf`

整数字面量:
- 支持前导正负

浮点字面量:
- 支持前导正负
- 不支持 '.' 起始
- 支持科学计数法

字符串字面量:
- 单行: `"aabbcc \" ???"` json 风格转义
- 多行:
`````infd
````text
???? aabbcc "??" ```
````
`````
类似 "MD代码块风格" 的多行字符串，可变长起始串。
起始串开始后直到第一个换行之间的内容被视为空白分割的tags。同时，该换行会被丢弃。且tags不会进入内容。
若起始围栏后没有换行符，则该行内容全部视为 tags（按空白分割），多行字符串的内容为空字符串。
多行字符串的内容截取到结束围栏之前。随后，先移除内容末尾的所有空格和制表符（' ' 和 '\t'），若剩余内容以换行符 '\n' 结尾，则再移除该换行符。
结束围栏的匹配规则为: 遇到与起始围栏等长的连续反引号序列立即结束，不附加任何上下文限制。
tags可为空，内容不做约束

> 匹配结束不是看到一个完整连续序列然后决定，而是字符流+计数器，一计数器达标就结束
> 需要注意的是，和MD不同，>=1 个反引号即能开始多行字符串

### 1.6 三态可空

可空类型的三种情形:
- `noexist` 不存在，键不会出现在解析结果中
- `null` 存在但为 null，键会出现，但值为 null
- `对应的value` 存在，键存在，且值为 value

> 三态仅对 **dict 字段**有意义；`noexist` 出现在**数组元素**中无意义，
> 编译器报错并视为 `null`（保留位置）。
> **与约束的交互**：字典约束 `has` / `field` 将 `noexist` 字段视为**不存在**
> （`has(noexist字段)` 不满足、`field(noexist字段, c)` 视为字段缺失）——见 §1.2.1 字典约束。

### 1.7 标识符与关键字

标识符（字段名、模板名、`$` 引用名、JSON path 键、约束名统一适用）:

- 组成: 字母或下划线起始，后接字母/数字/下划线（`[A-Za-z_][A-Za-z0-9_]*`）
- 大小写敏感

字面量关键字（词法层保留，不可作标识符）:
- `true` / `false` / `null` / `noexist` / `nan`

上下文相关关键字（可作普通标识符，仅在特定语法位置被识别）:
- `import` —— 仅在 `!env` / `!file` / `!from` 之后被识别
- `as` —— 仅用于导入别名与 `$name as type` 转换
- `inf` 本身是普通标识符；`+inf` / `-inf` 由数字词法识别为浮点字面量

### 1.8 导入命名空间（$ 引用）

`!env` 与 `!file` 的导入结果绑定到**命名空间**，引用须以 `$` 起始:

语法:
- `$name` —— 引用命名空间中的 `name`
- `$name as type` —— 显式类型转换，type ∈ `bool` | `int` | `float` | `str`

命名空间填充:
- `!env import NAME` → 绑定 `NAME`；`!env import NAME as NEW` → 绑定别名 `NEW`
- `!file ... import ... as name` → 绑定别名 `name`

规则:
- 同一别名重复绑定（env 与 env / env 与 file）→ 错误，保留先到者
- 引用未定义的 `$name` → 警告（`dollar.undefined`），该字段取 `null`（不中断编译）

转换规则（`as`）:
- `as bool`: `"true"` / `"1"` → `true`，`"false"` / `"0"` → `false`（不分大小写）
- `as int`: 正负整数，不支持小数
- `as float`: 正负、科学计数、点起始
- `as str`: 原样字符串

## 2. 模板

### 2.1 模板定义

基础语法:
- `~TemplateName { field_def, ... }`
- `~TemplateName(config=value) { field_def, ... }`

规则:
- 模板名遵循标识符规则（字母/下划线起始，字母/数字/下划线组成）。
- 模板内部字段**必须**带有约束
- 默认值 `= default` 可选，省略表示该字段为**必填字段**（实例化时必须提供）。
- 必填字段和非必填字段不可交错且必填字段必须在非必填字段前
  （例外：`positional=false` 的模板无位置参数绑定，允许必填与可选交错）
- 模板内部允许嵌套字典、数组、甚至其他模板调用。
- 同一个文件中，模板名不可重复定义。
- 支持配置模板的一些行为

示例:
```infd
~Features {
    caching: <?> = noexist,
    compression: bool = true,
}

~Server {
    host: str = "0.0.0.0",
    port: <int, range(1, 65535)> = 80,
    features: <Features> = Features(),
    tags: <list, each(str)> = ["web"],
}

~Database {
    name: str,
    host: str = "localhost",
    port: int = 5432,
    pool_size: <int, range(1, 100)> = 10,
}

~AllowExtra(allow_extra=true) {}
```

上例中 `Database.name` 省略了默认值，因此实例化 `Database` 时必须提供 `name` 参数。

支持的配置参数:
- `allow_extra: bool` 默认 `false` 设置为 `true` 来允许扩展属性
- `positional: bool` 默认 `true`, 设为 `false` 禁止位置参数
- `description: str?` 默认 `null`, 支持设为任意字符串，用于元数据

### 2.2 模板实例化

模板实例化是将模板展开为具体字段集的过程。

基础语法:
- `field_name = TemplateName(pos_arg1, pos_arg2, named_arg = value,)`
- `field_name TemplateName(...)` 省略等号, 等价于 `field_name = TemplateName(...)`

参数规则:
- **位置参数**在前，**命名参数**在后，不可交错。
- **位置参数**只能匹配必填字段，只有必填字段参与位置参数匹配
> 如果没有必填参数，不能使用位置参数
- 位置参数按模板字段的**定义顺序**依次绑定。
- 命名参数按**字段名**匹配，覆盖对应字段的默认值。
- 同一字段同时以位置和命名参数提供 → **错误**
- 未提供的可选字段使用模板默认值。
- 未提供的必填字段触发语义错误。

示例:
```infd
# 全默认
api Server()

# 位置参数
db Database("mydb")

# 命名参数覆盖指定字段
cache Server(host="redis.internal", port=6379)

# 命名参数位置无关
cache_backup Server(port=6379, host="redis.internal_backup")

# 嵌套字典中使用
backend {
    primary Server(host="primary.local"),
    replica Server(host="replica.local", port=8443),
}
```

展开语义:
模板实例化在语义分析阶段**原地展开**为 `dict`。展开后的字段与手写字段无区分，后续约束检查、默认值填充等流程完全一致。

### 2.3 模板即约束

模板定义时，其名称会自动注册为一个**同名校验器**，可在任意类型标注中作为约束使用。这是「类型是约束的特化」理念的自然延伸——模板不仅是语法宏，更是**用户自定义的结构类型**。

使用语法:
- `field: TemplateName = value,`
- `field: <TemplateName> = value,`
- `field: TemplateName? = value,` （可空）
- `field: <list, each(TemplateName)> [value,]` （与 each 组合）
- `field: <any(TemplateName, OtherTemplate)> = value,` （与逻辑约束组合）

约束语义:
当模板名作为约束校验某个值时（校验对象是**给定的值**，不填充任何默认值）:
1. 验证值必须是字典（`null` / 字面量直接失败）。
2. 逐字段校验值中出现的字段：
   - 值中**缺失**的字段：模板中该字段**无默认值**（必填）→ 校验失败
     （`missing_field`）；有默认值 → 放行（不报错，且**不注入默认值**，
     缺失保持缺失）。
   - 值中**存在**的字段：递归执行该字段声明的类型约束。
3. 严格模式（`allow_extra=false`，默认）下，值中存在模板未声明的额外字段
   → 校验失败（`extra_field`）。
4. 模板自身的结构级约束（`: <...>`）照常执行。

示例:
```infd
# 定义模板 → 自动生成同名校验器 Server
~Server {
    host: str = "0.0.0.0",
    port: <int, range(1, 65535)> = 80,
}

# 使用 Server 作为类型约束——手写dict也会被校验
hand_rolled: Server = {
    host = "manual.local",
    port = 3000,
}

# 与其他约束自由组合
cluster: <list, each(Server)> = [
    Server(host="node-1"),
    Server(host="node-2", port=8443),
]

# 可空引用
fallback: <Server?> = null

# 逻辑约束组合：既可以是 Server 也可以是 Database
resource: <any(Server, Database)> = Server(host="multi.local")
```

### 2.4 模板嵌套

模板内部可以引用其他已定义的模板:

```infd
~Endpoint {
    path: str = "/",
    method: <in("GET", "POST", "PUT", "DELETE")> = "GET",
}

~Service {
    name: str,
    server: Server = Server(),
    endpoints: <list, each(Endpoint)> = [],
}

# 实例化
user_service Service(
    name = "user-service",
    server = Server(port=8080),
    endpoints = [
        Endpoint(path="/users", method="GET"),
        Endpoint(path="/users", method="POST"),
    ],
)
```

### 2.5 模板引用与可见性

模板名按**书写位置**的可见性（scope）解析——即"当前文件里这个名字能看到什么"。

可见名来源:
- 当前文件内本地定义的模板
- 当前文件 `!from` 导入的模板（`as` 别名生效；无别名时用原名）

同名冲突规则:
- 本地定义与导入模板同名 → 错误
- 两个导入映射到同一可见名 → 错误，保留首个映射
- 导入模板与内置约束同名（如 `~str`）→ 错误，内置约束不可被遮蔽

模板身份（真名）:
- 真名 = 来源文件身份 + 本地名（磁盘 = resolve 绝对路径；内存 = 路径:mem:内容hash）
- **真名含来源路径**：不同路径的文件即使内容相同也是不同模板身份——模板内部
  `!from` 按定义文件所在目录解析，内容相同的文件其依赖语义可能不同，不能互相覆盖
  （纯内容寻址无法表达这一区别）
- 代价：真名随机器/路径变化（非内容寻址）；同文件内同名模板 → 错误
- `!from` 只建立「可见名 → 真名」的映射，不改变模板自身身份

嵌套模板引用:
- 模板内部引用其他模板，按其**定义文件**的可见性解析（导入是定义点可见）
- 跨文件引用链统一展开；循环引用安全退出

### 2.6 前向引用与自引用

前向引用（引用定义在之后的模板）:
- **同文件前向引用受支持**：模板可引用定义在其之后的模板。
  解析阶段先收集全部模板定义，语义阶段才展开，与书写顺序无关。
- **跨文件前向引用**：`!from` 导入的模板在导入声明之后可用（声明位置即绑定点）。

自引用（模板引用自身）:
- **作为类型约束可用**（递归类型）：如 `~Node { child: <Node?> = null }`。
  模板即约束的校验只检查**给定值**的结构，不会引发无限展开。
- **默认值禁止自引用**：模板的默认值不能引用模板自身（含间接自引用链）。
  编译器在展开前对「默认值引用图」做**静态环检测**，发现环即报错，不运行时展开。
- 合法写法：可空引用 + 默认 `null`，嵌套由调用方在值中显式构造：

```infd
~Node {
    child: <Node?> = null     # ✅ 可空自引用 + 默认 null
    # child: Node = Node()    # ❌ 默认值自引用 → 无限展开报错
}
n = Node(child = Node(child = Node()))   # 有限嵌套，合法
```

## 3. 外部导入

> **导入语句共同规则**：导入项之间必须用逗号分隔（不接受换行/空格分隔）；且整个
> 导入语句必须以**换行或文件末尾**结尾——同一行逗号后不能再接其他语句
> （见 §1.1「逗号换行等价（双向）」的导入例外，`!env` 与 `!file`/`!from` 同等适用）。

### 3.1 环境变量导入

> 环境变量导入不直接注入，需要使用 `$` 起始来在导入空间中找查目标

基础语法:
- `!env import NAME`
- `!env import NAME as NEW_NAME`

使用:
- `user_name = $NAME` 默认为字符串
- `user_id = $USER_ID as int` 支持转换，bool | int | float

转换规则:
- `as bool`: `("true", "1") | ("false", "0") -> true | false` 不分大小写
- `as int`: `"NUMBER" -> NUMBER` 支持正负，不支持小数
- `as float`: `"NUMBER ->" NUMBER` 支持正负，科学计数，点起始

### 3.2 模板导入

基础语法:
- `!from "Path to .inft file" import Template1, Template2`
- `!from "Path to .inft file" import Template1 as T1`

Path规则:
- 路径分割符: unix 风格 `/`（语言内**只允许** POSIX 风格，不接受 `\`）
- 相对路径: 相对路径起始点为导入所在文件的位置
- 支持绝对路径
- Windows 盘符: 写作 `/c/XXX/xxx/x.inft`（小写单字母 = 盘符）
- **跨平台自动映射**: 同一份 .infd 在 linux/windows/mac 均可用——访问文件系统时
  编译器按当前平台把 `/c/...` 映射为 `C:\...`
- **Windows 无盘符绝对路径**: `/usr/local` 这类不带盘符的绝对路径在 Windows 上
  按**当前盘根**（base 所在盘）处理，如 `C:\usr\local`——与 Linux/mac 的「根」语义
  不同，这是平台差异而非错误；跨平台路径建议始终显式写盘符（`/c/...`）

> glob 白名单统一按语言内 POSIX 形式匹配
> 文件内存在的模板定义不能和导入的模板冲突。否则是错误

使用:
- 同正常模板
- 无需 $ 前缀

### 3.3 现有配置导入

> 配置导入不直接注入，需要使用 `$` 起始来在导入空间中找查目标

基础语法:
- `!file "Path to config file" as yaml import .a.b.c as c`

Path规则同模板导入

导入规则:
- `as`: 可写可不写，不写默认看文件后缀，支持yaml，json，toml
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
!file "example.json" as json import .a.b[0]."c" as c
```
起始的`.`表示从文件根开始寻址

使用:
```infd
!file "example.json" as json import .a.b[0]."c" as c, .a.b as b

example_c = $c
example_list: <list, each(dict)> = $b

!file "example.json" as json import . as example

all_data = $example
```

## 4. 词法与解析细节

### 4.1 流水线与容错

```
chars → RawTokenizer → FinalTokenizer → Parser
```

- 词法/语法错误**不中断**：收集为诊断（Diagnostic）继续解析（容错）
- 解析器为 LL(1) 递归下降；错误恢复用合成 token 保证类型安全、始终前进
- 空源码 → 空配置（非错误）

### 4.2 导入关键字在词法层组合

- `!env` / `!file` / `!from` 由词法层组合为单一 token（避免语法层二义）
- 单独的 `!` 或 `!` 后跟其他内容 → 词法错误

### 4.3 顶层语句

顶层以**逗号或换行**分隔的语句（二者等价，可混用；导入语句内部仍强制逗号，见 §3.2）:
- 字段定义（含省略等号形式 `name {...}` / `name [...]`）
- 模板定义 `~Name {...}`
- 导入语句 `!env` / `!file` / `!from`
- 结构级约束 `: <...>`

### 4.4 JSON path 语法（!file 导入用）

```
.a.b[0]."c"
```

- 以 `.` 起始，从文件根寻址
- 段 = `.标识符` | `."字符串"` | `[整数下标]`
- 第一个段可以是 `.标识符` 或 `."字符串"`；`.` 后无有效段（如仅有 `.`）→ 视为导入整个文件
- **首段不能以标识符 `as` 作键**：`.` 后紧跟标识符 `as` 会被解析为整文件导入的
  别名关键字（`import . as all`），而非路径段。若根对象恰有名为 `as` 的键，
  用字符串段形式 `."as"` 显式写出（如 `import ."as" as v`）。

### 4.5 数字词法（补充）

- `nan` / `+inf` / `-inf` 为浮点字面量
- 无效数字（无数字、畸形符号/指数）→ 词法错误
- 其余规则见「1.5 字面量」
