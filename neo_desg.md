# InfinityData Language 设计文档

## 0. 基础设定

### 0.1 编码

本语言唯一合法的编码为 utf-8 NO BOM LF

### 0.2 文件类型

采用如下两种后缀名:
- .infd 允许模板定义和数据定义
- .inft 仅允许模板定义

## 1. 基础语法

### 1.1 字段定义

基础语法:
- 简单键值对 `name = default,`
复合值语法:
- `a_list = [a, b, c,]` 值之后必须有逗号，尾值后的逗号可选
- `a_dict = {a = 1, b = 2,}` 键值对后必须有逗号，尾值后的逗号可选

特殊规则:
- **省略等号**：对于复合值（字典、数组等）字段，等号可省略，如 `server { port = 8080 }`
- **省略逗号**: 对于任何需要逗号的地方，可以用换行替代

### 1.2 约束

基础语法:
- `key: constraint = default,`
- `key: <constraint, ...> = default,`


内置类型约束:
- `?`
- `object`，`int`, `str`, `bool`, `float`, `list`, `dict`
- `object?`, `int?`, `str?`, `bool?`, ...

内置一般约束:
- `range(ge, le)`
- `size(ge, le)`
- `each(constraint)`
- `in([choice, ...])`
- `ip`, `ip4`, `ip6`
- `regex("re")`

逻辑约束:
- `not(constraint)` 内部约束不满足则满足
- `any(constraint_a, constraint_b, ...)` 内部约束有任意多个被满足则满足
- `one(constraint_a, constraint_b, ...)` 内部约束只有一个被满足则满足
- `all(constraint_a, constraint_b, ...)` 内部约束全部满足则满足

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

字符串字面量:
- 单行: `"aabbcc \" ???"` json 风格转义
- 多行:
`````infd
````text
???? aabbcc "??" ```
````
`````
MD风格多行字符串，可变长起始串，同md，支持起始后缀标注
起始符后的空白和换行会被丢弃。同时结束符前的最后一个换行和空白会被丢弃

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
    features: dict {
        caching: <?> = exist,
        compression: bool = true,
    },
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
cache Server("default_cache", host="redis.internal", port=6379)

# 命名参数位置无关
cache_backup Server("backup_cache", port=6379, host="redis.internal_backup")

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

### 2.5 跨字段断言

> `assert` 仅允许写在模板内部，用于表达字段之间的约束关系。

基础语法:
- `assert condition, "错误信息"`

规则:
- `assert` 只能在模板（`~Template { ... }`）内部使用。
- `condition` 支持引用同模板中定义的字段名。
- `condition` 支持 `and`, `or`, `not`, `==`, `!=`, `>`, `<`, `>=`, `<=`, `in(...)` 运算符。
- `"错误信息"` 为必填，断言违反时作为诊断消息输出。
- 实例化或手写 dict 满足模板约束时，所有 `assert` 均需通过。
- **不允许多层嵌套**：`assert` 在模板的顶层字段作用域执行，字段引用无歧义。

示例:
```infd
~Server {
    port: int = 80,
    tls: bool = false,
    debug: bool = false,
    mode: <str, in("production", "staging")> = "production",

    assert port > 1024 or not debug, "debug 模式下端口必须大于 1024"
    assert (port != 443) or tls, "使用 443 端口时必须启用 TLS"
    assert mode != "production" or tls, "生产环境必须启用 TLS"
    assert port != 80 or mode != "production", "生产环境不允许使用默认端口 80"
    assert port in (80, 443, 8080, 8443) or port > 1024, "非标准端口必须大于 1024"
}

# 实例化：所有 assert 在语义分析时校验
my_server = Server(port=443, tls=true)
# ✅ 通过: port=443 → (443!=443) or true → true

# 违反时获得明确的错误信息
bad_server = Server(port=443, tls=false)
# ❌ 断言违反: "使用 443 端口时必须启用 TLS"
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

Path规则:
- 路径分割符: unix 风格 `/`
- 相对路径: 相对路径起始点为导入所在文件的位置
- 支持绝对路径
- Windows路径转义 `C:\XXX\xxx\x.inft` -> `/c/XXX/xxx/x.inft` 盘符转换为小写

> 文件内存在的模板定义不能和导入的模板冲突。否则是错误

使用:
- 同正常模板

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