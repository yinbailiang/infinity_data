# 基础语法

> 本页属于 InfinityData 语言参考，章节编号沿用完整规范（§x.y）。

## 1.1 字段定义

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
- **逗号换行等价（双向）**：除导入语法（`!from p"a" import X, Y` 必须用逗号和尾最后换行）外，
  任何需要逗号/换行的地方都可用另一方替代——顶层同样接受逗号分隔，
  任何不包含!特殊语句的文件（含模板定义、字段、结构级约束）可压缩成一行：
  `a = 1, b = [1, 2], ~T { x: int = 1 }, c = T(x = 2),`

## 1.2 约束

### 1.2.1 字段约束

基础语法:
- `key: constraint = default,`
- `key: <constraint, ...> = default,`

约束列表与约束参数同样以逗号或换行分隔（`<int\nrange(1, 10)>` / `range(1,\n10)` 合法；
空格不构成分隔）

内置类型约束:
- `?` 值只能是 `null`（键存在、值为 null）
- `!` 值只能是 `noexist`（键不存在）
- `object` 任何不是 `null` 或者 `noexist` 的值
- `int`, `str`, `bool`, `float`, `list`, `dict` 字面意思
- `object?`, `int?`, `str?`, `bool?`, ... 可空语法糖（等价 `any(T, ?)`，仅允许 null）
- `object!`, `int!`, `str!`, ... 可缺失语法糖（等价 `any(T, !)`，仅允许键不存在）
- `int?!` / `int!?` 两者都允许（等价 `any(T, ?, !)`；推荐 `?!`，`!?` 会告警）

内置一般约束:
- `range(ge[, le])` 数值范围。**省略规则**：单参数 `range(ge)`（或尾逗号 `range(ge,)`）
  = **仅下限**（值 ≥ ge，上界不限）；双参数 `range(ge, le)` = **闭区间**
  （ge ≤ 值 ≤ le）。**下界不可省略**：`range(, le)` 空参数位是语法错误
  （`parse.unrecognized_constraint`）；至少 1 个参数（`range()` 非法）。
  参数须为数值（int / float）
- `size(ge[, le])` 集合大小或字符串长度。省略规则与 `range` 一致：`size(ge)` / `size(ge,)`
  = **仅下限**（大小 ≥ ge）；`size(ge, le)` = **闭区间**；下界不可省略（`size(, le)` 语法错误）；
  至少 1 个参数（`size()` 非法）
- `each(constraint)` list 每个元素均满足约束则满足，dict 每个键的值均满足则满足
- `in(choice, ...)` 值必须在给定选项中
- `ip`, `ip4`, `ip6` IP 地址格式
- `regex("re")` 正则全匹配（也适用于 path：按 POSIX 字符串全匹配，如
  `regex(".*[.]pem")` 匹配 `.pem` 结尾的路径）
- `email` 邮箱格式
- `url` URL 格式
- `uuid` UUID 格式
- `hostname` 主机名格式
- `positive` 正数 (> 0)
- `path` 路径（语言内 POSIX 形式，§1.4 独立基础类型）——值必须是 **path 类型**
  （`p"..."` 字面量 / `$x as path` 转换产生）；**字符串不满足 path**——str 与 path
  相互独立、无隐式互转，str 值须经 `as path` 显式转换（§1.8）才能作为路径使用
- `same_target(path)` 词法解析（折叠 `.` / `..`，纯字符串操作）后与参数 path
  **指向同一目标**——不触碰文件系统、不解引用符号链接：纯语法、可复现
- `same_name(str)` 路径的 basename（最后一段）等于指定字符串
- `extension("json", ...)` 路径扩展名匹配任一（参数不带前导点；无扩展名不匹配）
- `negative` 负数 (< 0)
- `nonnegative` 非负数 (>= 0)
- `eq(value)` 等于指定值
- `unique` 集合元素不重复

字典约束:
- `has(key)` dict 包含指定键则满足
- `field(name, constraint)` 对某个field进行约束，如果field不存在或者约束失败，则不满足

数组约束:
- `position(index, constraint)` 对 list 指定下标（0-based）位置的元素进行约束；
  下标越界（元素不存在，含负数）或者约束失败，则不满足。index 必须是非负整数
  （0 / 1 / 2 / ...），与 `field` 互补——`field` 定位 dict 字段、`position` 定位 list 元素：
  ```infd
  first_is_int: <list, position(0, int)> = [1, "x"]        # ✅ 元素 0 是 int
  second_in_set: <list, position(1, in("a", "b"))> = ["x", "a"]  # ✅ 元素 1 ∈ {a, b}
  head_ok: <list, position(0, Server)> = [Server(), {}]     # ✅ 与模板即约束组合
  ```

> **与三态可空的交互**：`noexist` 字段（键不出现）对 `has` / `field` 均视为**不存在**——
> `has(noexist字段)` 不满足、`field(noexist字段, c)` 视为字段缺失（不满足）。
> 由此「可选字段（默认 `noexist`）+ 结构级约束」可自然表达「至少声明其一」:
> ```infd
> ~ResourceSpec {
>     requests: <dict?!> = noexist,
>     limits: <dict?!> = noexist,
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

文件系统约束（构建期校验，与导入同属**当前机器**文件系统状态）:
- `exist` 路径存在（lstat 成功，file/dir/link 任一）
- `dir` 路径是目录
- `file` 路径是普通文件
- `link` 路径是符号链接

> 与 `!file` / `!from` 一样，构建期访问本机文件系统（无跨机器迁移性承诺）；
> 授权复用沙盒的 **allow_files** 白名单。越出沙盒 → `constraint.path_denied`：
> **警告 + 失败**（约束不满足但诊断为 WARNING，不构成硬编译错误；组合约束
> `all` / `any` / `one` 的汇总诊断随子失败降级，保持软失败）。
> 组合表达：`field: <path, exist>` —— 先保证合法路径，再检查存在性
> （`dir`/`file` 跟随符号链接（stat），`link` 判定链接本身（lstat））。

特殊规则:
- **单约束可省略尖括号**: `field: int = 10` 等价于 `field: <int> = 10`
- **默认all**: <a, b, c> 等价 all(a, b, c)
- **可空 / 可缺失约束**：`type_c?` 等价 `any(type_c, ?)`（值或 null）；`type_c!` 等价
  `any(type_c, !)`（值或键不存在）；`type_c?!` / `type_c!?` 等价 `any(type_c, ?, !)`
  （推荐 `?!`；`!?` 等价但报 `parse.postfix_order` 警告）。`?` / `!` 与常规约束的
  满足集合不相交，故与 `one` 语义等价，用 `any` 更贴近「类型或空」的直觉
- 裸标记也可组合：`?!` / `!?` 等价 `any(?, !)`（null 或键不存在），
  `x: ?! = null` 与 `x: <?!> = null` 均合法

### 1.2.2 结构级约束（dict 级约束）

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


## 1.3 注释

单行:
- 以 `#` 开始，直达该行结束

多行:
- 以 `#+` 开始，遇到 `#-` 结束
- `#` 可以有任意多个 `+` 或 任意多个 `-` 标记，但是开始和结束的标记数量必须相等
- 开始标记为 `#` + `+` * N 则结束标记为 `#` + `-` * N
- 多行注释外的未匹配的起始或结束token都是词法错误

## 1.4 基础类型

内置类型:
- `object` 所有类型都是 object，除了 `?` / `!`
- `?` 纯可空类型：值只能是 null
- `!` 纯可缺失类型：值只能是 noexist（键不存在）
- `bool` 布尔值， true 或者 false
- `int` 有符号整数，无限精度
- `float` 无限精度10进制浮点
- `str` utf-8编码字符串，无尾0
- `path` 路径（语言内 POSIX 形式；值模型用专有类型表示，`p"..."` / `as path` 产生）。
  **独立基础类型，与 `str` 无隐式互转**：字符串不是路径（`path` 约束拒绝 str，§1.2.1），
  str 值须经 `as path` 显式转换（§1.8）才能作为路径使用
- `list` 数组类型，内部元素可以是任何类型
- `dict` 字典类型，键名为utf-8无尾0字符串，值是 object

## 1.5 字面量

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

路径字面量:
- `p"..."` 路径字面量：`p` 前缀 + 双引号单行字符串（json 风格转义，同单行字符串）
- `p` 与 `"` 之间不能有空白；`p` 后非 `"` → 按普通标识符处理
- 产生 **path 类型**的值（语言内 POSIX 形式）：`p"/etc/certs/a.pem"`、`p"./tpls/base.inft"`
- **path 与 str 是独立类型**（§1.4）：`p"..."` 的产物不是字符串——`str` / `size` /
  `regex` 等字符串约束对它不适用；空串 / NUL 等无法构成路径 → 词法错误
  （`tokenize.invalid_path`）

## 1.6 三态可空

可空类型的三种情形:
- `noexist` 表达配置键本身不存在
- `null` 键存在但值为 null，键会出现，但值为 null
- `对应的value` 存在，键存在，且值为 value

> 三态仅对 **dict 字段**有意义；`noexist` 出现在**数组元素**中无意义，
> 编译器报错并视为 `null`（保留位置）。
> **与约束的交互**：字典约束 `has` / `field` 将 `noexist` 字段视为**不存在**
> （`has(noexist字段)` 不满足、`field(noexist字段, c)` 视为字段缺失）——见 §1.2.1 字典约束。
> **与 `$` 引用 / `as` 转换的交互**：空字面量（`null` / `noexist`）经 `$name as type`
> 转换**保持传播**（`null → null`、`noexist → noexist`），不因显式 `as` 丢失三态
> 语义——见 §1.8 转换规则。
> **Python 域表示（实现层）**：`noexist` 是表达「**键不存在**」这一态的选项，
> 与 `null`（键存在但为 null）严格区分。忠实互转层
> （`python_to_std` / `std_to_python`）用 `NOEXIST` 哨兵承载该态——
> `{'a': NOEXIST}` → 字段 a 为 noexist（键不出现）；`{'a': None}` → 字段 a 为
> null（键出现、值为 null）。转换层**默认无损保留**该态；输出投影
> （`CompilationResult.value`）按本节承诺丢弃（键不出现）。
> **参考用途（emit 层）**：`EmitConfig.keep_noexist` 开启时，`to_json` / `to_yaml`
> / `to_toml` 将 noexist 输出为 `{"__type__": "noexist"}` 自描述标记。

## 1.7 标识符与关键字

标识符（字段名、模板名、`$` 引用名、JSON path 键、约束名统一适用）:

- 组成: 字母或下划线起始，后接字母/数字/下划线（`[A-Za-z_][A-Za-z0-9_]*`）
- 大小写敏感

字面量关键字（词法层保留，不可作标识符）:
- `true` / `false` / `null` / `noexist` / `nan`

上下文相关关键字（可作普通标识符，仅在特定语法位置被识别）:
- `import` —— 仅在 `!env` / `!file` / `!from` 之后被识别
- `as` —— 仅用于导入别名与 `$name as type` 转换
- `is` —— 仅在 `!assert` 的值与约束之间被识别
- `inf` 本身是普通标识符；`+inf` / `-inf` 由数字词法识别为浮点字面量

## 1.8 导入命名空间（$ 引用）

`!env` 与 `!file` 的导入结果绑定到**命名空间**，引用须以 `$` 起始:

语法:
- `$name` —— 引用命名空间中的 `name`
- `$name as type` —— 显式类型转换，type ∈ `bool` | `int` | `float` | `str`

**按文件就地解析**（per-file namespace）:
- 每个文件（主 `.infd` 与每个被 `!from` 导入的 `.inft`）有**独立**的 `$` 命名空间
- 文件内的 `!env` / `!file` / `!var` 绑定到**本文件**的命名空间
- 模板内部（默认值 / 模板体）的 `$` 引用按其**定义文件**的命名空间就地解析——
  与模板名「定义点可见」（§2.5）对称：**一个文件里能看到的名字（模板名、`$` 名）都在本文件解析**
- 顶层字段的 `$` 引用用主文件（`.infd`）命名空间
- **跨文件完全隔离**：模板不能隐式引用调用方的 `$`；调用方数据传模板只经**参数**（`Server(cfg = $cfg)`）
- 未定义的 `$name` 在本文件空间查不到 → `dollar.undefined` 警告取 null（不中断编译）

命名空间填充:
- `!env import NAME` → 绑定 `NAME`；`!env import NAME as NEW` → 绑定别名 `NEW`
- `!env import NAME1 as NEW1, NAME2, ...` → 一次导入多个（逗号分隔，`as` 别名可选）
- `!file ... import ... as name` → 绑定别名 `name`
- `!var <值> import ... as name` → 绑定别名 `name`

规则:
- 同一别名重复绑定（同文件内 env / env / file / var）→ 错误，保留先到者
- 引用未定义的 `$name` → 警告（`dollar.undefined`），该字段取 `null`（不中断编译）
- `!var` 求值结果携带的约束（来自模板展开 / dict 字面量）在**编译期**执行，
  诊断路径显示为 `$别名`；不依赖它是否被 root 引用

导入真名（import identity）:
- 每个 `$` 绑定（`!env` / `!file` / `!var` 项）有**确定性真名**（来源 + 取值哈希）：
  - `!env import NAME` → `SHA256("env" || NAME || 值)` —— **环境变量的值参与哈希**
  - `!file p"path" as fmt import <path> as x` → `SHA256(fmt || jsonpath || 文件内容哈希)`
    （**不含文件路径**：内容 + 格式 + 投影相同、路径不同的文件共享真名——路径无关的源材料去重）
  - `!var <expr> import <path> as x` → `SHA256(canon(expr) || path || 依赖绑定真名)`
    （`!var` 传递其依赖的 env / file 取值：`!var $PORT import . as p` 会因 env 值变化而变）
- **环境差异必须可见**：同一份配置在不同机器 / 环境下 env 值不同 → 真名不同。
  「静默漂移」比「身份不稳定」更危险——产物身份应反映真实输入，
  跨机器一致性不能靠假装环境相同来维持
- 其余维度（模板内容、`!file` 内容）相同 → 真名相同；诊断显示本地名（`$x`）；
  真名 hash 作映射键与产物签名
- 真名是**身份/签名维度**，不参与解析（解析仍按名字查本文件命名空间）
- 模板身份纳入其 `$` 引用的导入真名（§2.5）——模板签名覆盖数据依赖（含 env 取值）

转换规则（`as`）:
- **作用于任何导入空间的字符串数据**（`!env` / `!file` 含 `raw` / `!var`），与来源无关：
  命名空间统一存 StdValue，`$name as type` 只要求值是字符串（或其他标量）；
  非字符串结构化值（list / dict）应用 `as` → 错误（`dollar.convert_unsupported`），
  容错原样返回该值并继续编译（写了 `as` 就必须转换，不静默忽略）
- **空字面量保持传播**：`null` / `noexist` 经 `as` 转换**原样保持**（`null → null`、
  `noexist → noexist`），不做转换、不产生警告、不回退——三态可空语义不因显式
  `as` 而丢失（`noexist` 字段在输出中依旧消失）
- `as bool`: `"true"` / `"1"` → `true`，`"false"` / `"0"` → `false`（不分大小写）
- `as int`: 正负整数，不支持小数
- `as float`: 正负、科学计数、点起始
- **str ↔ path 的唯一桥梁是显式 `as` 转换**（§1.4 两者独立、无隐式互转）：
  字符串要当路径用必须 `as path`，路径要当字符串用必须 `as str`
- `as path`: 字符串 → path（合法则包装为路径值；非法 → 警告 + 保留原字符串）；
  已是 path 的值原样返回
- `as str`: 字符串化——任意字面量按**语言字面量风格**转字符串，可 round-trip 还原：
  `int` / `float` → 十进制（`42`、`1.5`）；`bool` → `true` / `false`；
  `float` 特殊值 → `nan` / `+inf` / `-inf`；path → POSIX 字符串（`/c/foo`）；字符串原样

## 1.9 编译期断言（`!assert`）

语法:
- `!assert <值表达式> is <约束>`

语义:
- 值按**所在文件** scope 求值（字面量 / 数组 / 对象 / 模板调用 / `$` 引用）
- 约束在编译期执行；成功静默，失败报具体 `constraint.*` 诊断，位置指向断言值
- 约束失败按诊断自身级别处理（ERROR 使编译失败；WARNING 仅警告）
- 断言**不产生输出字段**，也不参与模板身份
- 主 `.infd` 与 `.inft` 均可使用；`.inft` 内按该文件 `$` 命名空间就地求值
- `is` 后缺少约束 → `parse.assert_missing_constraint`

```infd
!assert [1, 3, 4] is <list, each(int)>
!assert p"." is path

!var 42 import . as answer
!assert $answer is int
```
