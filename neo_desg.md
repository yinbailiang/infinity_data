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
- **重复键为错误**：同一 dict（含顶层 root、模板定义内、解包合并后）中同名键出现
  多次 → 错误（`dict.duplicate_key`），容错保留先到者、继续编译。模板参数覆盖默认值
  （§2.2）**不构成**重复键——它是参数绑定而非同 dict 双字段。模板调用命名参数重复
  → `template.dup_argument`（见 §2.2）
- **逗号换行等价（双向）**：除导入语法（`!from "a" import X, Y` 必须用逗号和尾最后换行）外，
  任何需要逗号/换行的地方都可用另一方替代——顶层同样接受逗号分隔，
  任何不包含!特殊语句的文件（含模板定义、字段、结构级约束）可压缩成一行：
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
>     : <one(has(requests), has(limits))>,   # 必须只提供一个；都没提供则违反
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
- 命名参数按**字段名**匹配，覆盖对应字段的默认值（覆盖默认值不构成重复键，见 §1.1）。
- 同一字段同时以位置和命名参数提供 → **错误**
- **同一命名参数重复提供**（`T(a = 1, a = 2)`）→ **错误**（`template.dup_argument`）
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
- 真名 = **直接依赖组合哈希**（闭包经哈希嵌套隐式捕获）+ 本地名：
  `identity(T) = SHA256(canon(T) || sorted(identity(直接依赖模板)))`，
  其中 `canon(T)` 是模板 T 定义的 **AST 规范化结构哈希**（注释/空白不影响身份）；
  直接依赖 = T 定义文件的 `!from` 解析结果 + 同文件引用，按名排序保证确定性
- **闭包无需显式计算**（Merkle 式）：直接依赖的 identity 已含其自身依赖子树，
  递归一层即间接包含全部依赖闭包——`identity(A)` 通过哈希嵌套自动覆盖
  A→B→C→…→叶子整条链，不构建传递闭包集合
- **依赖语义差异被捕获**：模板内部 `!from` 按定义文件所在目录解析，内容相同的文件
  若依赖不同 → 依赖 identity 不同 → 组合 hash 不同 → 不同身份（保留 §2.5 原「区分
  依赖语义」的能力，但不再依赖路径）
- **可复现**：内容与依赖闭包相同 → 真名相同，与机器/路径无关——支持跨机器签名、
  可审计、可 diff（修复原「真名随路径变化」的硬伤）
- **环处理**：递归计算时维护 DFS 栈，环内依赖退化为「该模板内容 hash」（不递归）——
  终止、确定、路径无关（轻量栈标记，非完整环分析）
- 跨文件内容+依赖相同的模板共享同一身份（导入去重）；同文件内同名模板 → 错误
- 诊断显示用本地名（`name`，如 `template.undefined` 显示 `Server`）；
  真名 hash 仅作映射键与产物签名
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

### 2.7 解包（dict / list unpacking）

> 值层组合：把导入数据或模板结果平铺合并进 dict / list。

基础语法:
- `**expr` —— dict 解包，展开键值对（用于 dict 值 / 模板调用命名参数）
- `*expr` —— list 解包，展开元素（用于 list 值 / 模板调用位置参数）

解包来源:
- `**{...}` / `**Template(...)` —— 编译期可见，键集合静态可知，冲突可静态发现
- `**$name` —— 导入数据（`!file` / `!env`），构建期已解析为具体值，键集合在
  构建期可见（重复键可静态检测）；约束在展开后于执行阶段照常校验
- **不支持 `**bare_identifier`**（裸标识符解包会引入变量引用语义，破坏纯声明式定位）

规则:
- 解包在 AST 构建（值构造）阶段展开为普通字段/元素，之后**一切照旧**
  （字段约束、结构级约束、降维输出不受影响）
- **键冲突一律错误**：解包后与已有键（含其他解包、显式字面量键、模板参数）同名 →
  错误（`dict.duplicate_key`），保留先到者、继续编译。`$` 引用在构建期已解析为
  具体值，故**所有冲突（含 `**$name` 来源）均可在构建期静态检测**，无运行时覆盖。
  dict 解包语义 = **无冲突并集（disjoint merge）**
- **三态可空保留**：解包出的 `noexist` 字段保持 noexist 语义（输出消失、
  `has`/`field` 视为不存在）；数组解包中混入 `noexist` → 沿用 `value.noexist_in_array`
- 模板调用中的解包：`**$cfg` 展开为命名参数，`*$list` 展开为位置参数；
  未知键照常走 `allow_extra` 放行或 `template.unknown_argument` 报错

示例:
```infd
base = { a = 1, b = noexist }
merged = { **base, c = 3 }          # b 保持 noexist
list_all = [ *parts, "suffix" ]
server = Server(port = 8080, **$tuning)
server2 = Multi(*$positional_list)
```

### 2.8 模板在 list 上展开（显式轴）

> 把外部裸列表**批量构造**为模板实例（map 语义），与 `each`（只校验不构造）互补。
> 语法致敬 C++ pack expansion：`...` 全语言只有一种含义——**展开/重复**，位置决定作用域：
> 参数级 `...` = 该参数随轴变化（本调用展开）；调用级（`)` 后）`...` = **展开向外传播**，
> 把本调用的展开结果作为**包围模板调用**的轴，整个嵌套模式逐元素重复。

基础语法:
- 参数级 `...` 后缀 = **展开轴**标记（位置/命名参数均可；与参数值来源无关——
  `$` 引用、字面量 list、模板构造 list 都能作轴）
- 有 ≥1 轴 → 调用**展开**，结果**恒为 list**；0 轴 → 普通单次调用
- 调用级（`)` 后）`...` = **展开传播**：本调用的展开结果（list）作为**包围模板调用**
  的轴继续展开——`B(A($list...)...)` ⟹ `[B(A(x)) for x]`
- 传播可链式：`C(B(A($list...)...)...)` ⟹ `[C(B(A(x))) for x]`（每层显式写 `...`）
- **多轴默认 zip**（等长配对）

```infd
nodes = Node(host = $hosts...)                   # 单轴：N 个实例
pairs = Node(host = $hosts..., port = $ports...) # 多轴 zip：等长配对
wrapped = B(A($hosts...)...)                     # 传播：整个模式逐元素重复 → [B(A(h))…]
chain = C(B(A($hosts...)...)...)                 # 链式传播：三层嵌套
all = [*Node(host = $hosts...)..., "extra"]      # 展开结果 splice 进数组
validated: <list, each(Node)> = Node(host = $hosts...)   # 展开 + each 双保险
```

**轴与解包可叠加**（外部数据生成的关键组合）:
```infd
!file "services.json" as json import . as services
# $services = [{name = "auth", port = 8080}, {name = "billing"}]

services = Service(**$services...)     # list[dict] 逐元素解包为命名参数再实例化
# → [Service(name="auth", port=8080), Service(name="billing")]
```

**展开传播（调用级 `...`）**:
- 传播把本调用的展开结果（list）**提升为包围模板调用的轴**：
  `B(A($list...)...)` = 对 `$list` 每个元素构造 `B(A(x))`
- 传播是**显式 opt-in**：`B(A($list...))`（无尾部 `...`）= 内层展开、B 收列表
  （k8s 的 `PodSpec(containers = Container(**$containers...))` 即此用法，语义不变）；
  加尾部 `...` 才把展开传出去
- 传播**逐层显式**：每层要传下去就在该调用后写 `...`；不加则展开止于本调用
- 传播目标必须是**包围的模板调用**；顶层字段 / dict 字段等非模板位置无处可传
  → 尾部 `...` 为 no-op（结果仍为该调用自身的展开 list）
- **尾部 `...` 但本调用无展开源**（自身无轴、也无内层传播而来）→ 报错
  （`template.expand_no_source`）

规则:
- **轴与解包可叠加**：轴参数可带 `**`（list[dict]）——每个元素（dict）经 `**` 解包
  为命名参数后再实例化一次（≡ Python `[Service(**s) for s in services]`）。外部裸
  数据与模板字段对齐时，`Template(**$list...)` 是「导入 → 生成」闭环的一行式
- **展开轴运行时必须是 list**：非 list → 报错（`template.expand_not_list`），
  不静默退化——保证「写了 `...` 就必须展开」的类型稳定性
- **zip 模式（默认）**：多轴按位置配对，长度不等 → 报错（`template.expand_length_mismatch`）
- **实例总数上限** `MAX_EXPAND`（如 10000）：展开实例总数超限 → 报错
  （`template.expand_too_large`），防止 `$` 数据源导致产物爆炸（可审计定位）
- 每个实例是**完整模板实例**：默认值注入 + 结构级约束（`: <...>`）照常执行
  ——这是与 `each`（只校验、不注入默认值）的本质分界
- `...` 只在模板调用参数上下文合法；普通值位置（`a = x...`）→ 语法错误
- **`...` 仅模板调用合法**：展开 = 对 list 每个元素应用模板构造（map），模式必须由
  模板提供；裸值表达式（`$list...` / `[1, 2, 3]...`）无构造语义 → 非法，
  平铺请用 `*`（`[*$list]`）。`...` 跟随模板调用遍布所有值位置
  （字段 / dict / list / `!var` / 模板默认值）
- **dict 轴不支持**：dict 展开请用 `**$dict` 解包进一次调用，避免语义重叠
- **优先级**: 先求解 `...` 展开再求解 `**`/`*`

与 `*` / `**` 的分工（三个展开符号）:

| 语法 | 语义 |
|---|---|
| `Template(*$list)` | `*`：1 次调用，list → N 个位置参数（std::apply） |
| `Template(**$cfg)` | `**`：1 次调用，dict → N 个命名参数（合并） |
| `Template($list...)` | `...`（参数级）：N 次调用 |
| `Template(A($list...)...)` | `...`（调用级/传播）：N 次调用，内层 A 的展开结果作本调用轴 |
| `Template($a..., $b...)` | 多轴 zip（默认）：N 次调用，等长配对 |

### 2.9 模板可变参数收集（模板配置）

> 通过**模板头部配置**声明「额外参数收集」，约束与实例化**完全复用普通字段机制**
> （零新约束语法、零特殊实例化路径）——收集字段就是模板里的普通字段。

基础语法（模板头部配置）:
- `extra_positional_vars = <字段名>` —— 收集**多余位置参数**（超出必填字段数）到指定字段（list）
- `extra_named_vars = <字段名>` —— 收集**未声明命名参数**到指定字段（dict）

```infd
~Service(extra_positional_vars = rest, extra_named_vars = extra) {
    name: str,
    port: <int, range(1, 65535)> = 80,
    rest: <list, each(str)> = [],
    extra: <dict, each(str)> = {},
}

s = Service("svc", "extra-pos", env = "prod", tier = "web")
# → name="svc", port=80, rest=["extra-pos"], extra={env="prod", tier="web"}（值过 each(str) 校验）
```

规则:
- **收集字段必须在模板中声明**：config 引用未声明字段 → 报错
  （`template.variadic_target_missing`）。收集值（list / dict）作为该字段的值，
  字段的**普通约束照常执行**——约束声明零新语法
- 收集字段通常为可选（默认 `[]` / `{}`）；收集为空时用字段默认值
- **与 `allow_extra` 二选一**：声明 `extra_named_vars` 时未声明命名参数**一律进收集字段**，
  不再走 `allow_extra` 的平铺放行——「平铺放行」与「收集受控」语义互斥
- `extra_positional_vars` 与 `positional=false` 并存 → 报错（自相矛盾）
- **模板即约束（校验身份）**：rest / extra 是普通字段，校验天然统一（零改动）
- **JSON Schema 映射**：`extra: <dict, each(str)>` → `additionalProperties: { type: string }`；
  `rest: <list, each(str)>` → 位置参数数组的 `items`

三个特性协同示例:
```infd
~App(extra_named_vars = extras) { extras: <dict, each(int)> = {} }
cfg = App(name = "x", **$tuning)                 # 解包 → 未知键进 extras，须全为 int
batch = App(name = "x", **$tuning...)            # 展开（zip）再 解包
```

### 2.10 本地注入（!var）

> 统一的本地 `$` 空间注入语句：**常量定义、组装、投影共用同一条语法**，
> 取代独立的 `!define` 与投影语句。

基础语法:
- `!var <值表达式> import [path] as <name>`

说明:
- `<值表达式>`：与字段值相同——字面量 / 复合值（含解包 `**`/`*`）/
  `$` 引用（含 `as type` 转换）/ 模板调用
- `[path]`：JSON path（§4.4），`.` = 整值
- `<name>`：`$` 空间别名

示例:
```infd
!var { timeout = 30, retries = 3 } import . as base      # 定义 dict 常量
!var [1, 2, 3] import . as nums                          # 定义 list 常量
!var { **$base, x = 1 } import . as merged               # 组装（解包合并）
!var $merged import .timeout as timeout                  # 投影取子字段
!var Server(port = 8080) import .host as host            # 模板实例投影
```

规则:
- **仅顶层可用**（模板内 / dict 字面量内不支持；模板内中间值用字段默认值表达）
- **不进输出**：`!var` 只绑定 `$` 空间，被 `$` 引用消费时才进入产物
- 与 `!env` / `!file` / `!from` 同属 `$` 空间注入语句族；同名冲突 →
  `namespace.duplicate`（保留先到者）
- source 可含 `$` 引用（**前向引用支持**）；依赖环 → 错误
  （复用模板默认值环检测思路，§2.6）
- path 取不到 → 错误（不静默 null，与 `!file` 一致）
- dict 解包语义照常（disjoint merge，重复键 → `dict.duplicate_key`，§2.7）

`$` 空间注入语句族:

| 语句 | source | 沙盒 |
|---|---|---|
| `!env import NAME as alias` | 环境变量 | 受控（§3.1） |
| `!file "path" import path as alias` | 外部文件 | 受控（§3.3） |
| `!var 值表达式 import path as alias` | 内存 / 字面量 | **无**（纯本地） |
| `!from "path" import T as T` | 外部模板 | 受控（§3.2，模板空间） |

vs 顶层字段:
- 顶层字段 `foo = 1` → **进输出**（你要产出它）
- `!var ... as foo` → **只进 `$` 空间**（你只当它原料）；产出经 `$foo` 引用进入字段
- **数据流单向**：`$` 引用只查 `$` 空间（`!env` / `!file` / `!var` 填充）；
  **顶层字段不在 `$` 空间，不可被 `$` 引用**（引用 → `dollar.undefined` 警告取 null）。
  管道中间态必须用 `!var` 绑定才能被后续 `!var` 引用；顶层字段是**终点**（进输出），
  不能回流进管道——保证「管道 → 输出」的单向性，杜绝隐藏循环

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

### 4.4 JSON path 语法（!file / !var 共用）

```
.a.b[0]."c"
.[0].name
```

- 以 `.` 起始，从根寻址
- 段 = `.标识符` | `."字符串"` | `[整数下标]`
- 第一个段可以是 `.标识符`、`."字符串"` 或 **`[整数下标]`**（首段下标合法，
  `.[0]` 直接取数组首元素）；`.` 后无有效段（如仅有 `.`）→ 视为导入整个文件
- **统一操作 StdValue**：`!file` 导入的数据先转 AST（:func:`python_to_std`）再投影；
  `!var` 求值结果本就是 StdValue，直接投影——两者共用同一套 path 语义
- **首段不能以标识符 `as` 作键**：`.` 后紧跟标识符 `as` 会被解析为整文件导入的
  别名关键字（`import . as all`），而非路径段。若根对象恰有名为 `as` 的键，
  用字符串段形式 `."as"` 显式写出（如 `import ."as" as v`）。

### 4.5 数字词法（补充）

- `nan` / `+inf` / `-inf` 为浮点字面量
- 无效数字（无数字、畸形符号/指数）→ 词法错误
- 其余规则见「1.5 字面量」
