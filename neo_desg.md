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
- `a_list = [a, b, c,]` 值之后必须有逗号，尾值后的逗号可选
- `a_dict = {a = 1, b = 2,}` 键值对后必须有逗号，尾值后的逗号可选

特殊规则:
- **省略等号**：对于复合值（字典、数组等）字段，等号可省略，如 `server { port = 8080 }`
- **省略逗号**: 对于任何需要逗号的地方，可以用换行替代，除了导入语法中使用的逗号

### 1.2 约束

基础语法:
- `key: constraint = default,`
- `key: <constraint, ...> = default,`
- `key: constraint [...],`
- `key: <constraint, ...> {...},`


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
- `object` 所有类型都是object
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
MD风格多行字符串，可变长起始串。
起始串所在行后续内容会被视为空白分割的tags
起始符后的空白和换行会被丢弃。同时结束符前的最后一个换行和空白会被丢弃

> 需要注意的是，和MD不同，>=1 个反引号即能开始多行字符串

### 1.6 三态可空

可空类型的三种情形:
- `noexist` 不存在，键不会出现在解析结果中
- `null` 存在但为 null，键会出现，但值为 null
- `对应的value` 存在，键存在，且值为 value

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
- 模板内部允许嵌套字典、数组、甚至其他模板调用。
- 同一个文件中，模板名不可重复定义（后者覆盖前者并产生警告）。
- 支持配置模板的一些行为

示例:
```infd
~Server {
    host: str = "0.0.0.0",
    port: <int, range(1, 65535)> = 80,
    features: <dict> {
        caching: <?> = noexist,
        compression: bool = true,
    }, # 注意，这里的内部dict作为默认值。模板不会为内嵌的dict默认值生成递归的校验
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

### 2.2 模板实例化

模板实例化是将模板展开为具体字段集的过程。

基础语法:
- `field_name = TemplateName(pos_arg1, pos_arg2, named_arg = value,)`
- `field_name TemplateName(...)` 省略等号, 等价于 `field_name = TemplateName(...)`

参数规则:
- **位置参数**在前，**命名参数**在后，不可交错。
- **位置参数**只能匹配必填字段，只有必填字段参与位置参数匹配
- 位置参数按模板字段的**定义顺序**依次绑定。
- 命名参数按**字段名**匹配，覆盖对应字段的默认值。
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
当模板名作为约束校验某个值时:
1. 验证值必须是字典。
2. 验证模板声明的所有字段存在。
3. 对每个字段，递归执行该字段的类型约束。
5. 不允许值中存在模板未声明的额外字段。可配置

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

### 2.5 模板级约束

> 以 `:` 起始，约束目标为模板实例化出的整个 dict。

基础语法:
- `: <constraint, ...>`
- `: constraint` 单约束可省略尖括号

规则:
- `:` 只能在模板（`~Template { ... }`）内部使用。
- 约束目标是模板对应的整个 dict，而非某个字段。
- 约束函数与字段级约束完全共用（同一注册表）。
- 所有 `:` 约束均需通过，否则为语义错误。

示例:
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

---

## 3. 外部导入

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
- 路径分割符: unix 风格 `/`
- 相对路径: 相对路径起始点为导入所在文件的位置
- 支持绝对路径
- Windows路径转义 `C:\XXX\xxx\x.inft` -> `/c/XXX/xxx/x.inft` 盘符转换为小写

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