# 模板

> 本页属于 InfinityData 语言参考，章节编号沿用完整规范（§x.y）。

## 2.1 模板定义

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
- 模板内部**字段名不可重复**：同名字段在**定义时**即报错（`dict.duplicate_key`，
  见 §1.1），容错保留先到者、继续编译；重复字段不会进入模板模型。
- 模板字段约束在**定义时静态校验**：未知约束名 → `constraint.unknown`，
  参数个数不符 → `constraint.arg_count`——无需实例化即可发现（未被实例化的模板
  不参与约束执行，否则这类错误永远不会被报出）。
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

## 2.2 模板实例化

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

## 2.3 模板即约束

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

## 2.4 模板嵌套

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

## 2.5 模板引用与可见性

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
  `identity(T) = SHA256(canon(T) || sorted(identity(直接依赖模板)) || sorted(import_identity(T 的 $ 引用)))`，
  其中 `canon(T)` 是模板 T 定义的 **AST 规范化结构哈希**（注释/空白不影响身份）；
  直接依赖 = T 定义文件的 `!from` 解析结果 + 同文件引用，按名排序保证确定性；
  `import_identity` = 模板 T 定义文件命名空间中其 `$` 引用对应绑定的**导入真名**（§1.8）
- **`$` 数据依赖纳入身份**：模板体/默认值中的 `$` 引用经定义文件命名空间映射为导入真名
  （叶子哈希，无递归）进入 identity——`!file`/`!env`/`!var` 来源变化 → 身份变化（可审计）；
  与「依赖语义差异被捕获」同源：模板依赖 + 数据依赖统一进哈希
- **闭包无需显式计算**（Merkle 式）：直接依赖的 identity 已含其自身依赖子树，
  递归一层即间接包含全部依赖闭包——`identity(A)` 通过哈希嵌套自动覆盖
  A→B→C→…→叶子整条链，不构建传递闭包集合
- **依赖语义差异被捕获**：模板内部 `!from` 按定义文件所在目录解析，内容相同的文件
  若依赖不同 → 依赖 identity 不同 → 组合 hash 不同 → 不同身份（保留 §2.5 原「区分
  依赖语义」的能力，但不再依赖路径）
- **可复现**：内容与依赖闭包相同 → 真名相同，与机器/路径无关——支持跨机器签名、
  可审计、可 diff（修复原「真名随路径变化」的硬伤）
- **环处理**（模板依赖环；文件级导入环见 §3.2）：递归计算时维护 DFS 栈，
  环内依赖退化为「该模板内容 hash」（不递归）——终止、确定、路径无关
  （轻量栈标记，非完整环分析）
- 跨文件内容+依赖相同的模板共享同一身份（导入去重）；同文件内同名模板 → 错误
- 诊断显示用本地名（`name`，如 `template.undefined` 显示 `Server`）；
  真名 hash 仅作映射键与产物签名
- `!from` 只建立「可见名 → 真名」的映射，不改变模板自身身份

嵌套模板引用:
- 模板内部引用其他模板，按其**定义文件**的可见性解析（导入是定义点可见）
- 跨文件引用链统一展开；循环引用安全退出

## 2.6 前向引用与自引用

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

## 2.7 解包（dict / list unpacking）

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
- **模板调用 `*` 拼接保持源码顺序**：`T(*[1, 2], 3, *[4], 5)` 的位置参数序列 =
  `[1, 2, 3, 4, 5]`——解包项在书写位置就地展开（≡ Python 语义），而非统一挪到
  显式位置参数之后；配合 `extra_positional_vars` 收集时，多余位置按此顺序入收集字段
- **解包与显式键/参数的「先到者」按源码顺序**：`{ x = 1, **$base }`（x 先到，$base.x
  为重复键）与 `{ **$base, x = 1 }`（$base.x 先到）保留结果不同；模板调用
  `T(**{ a = 1 }, a = 2)` 同理 a=1 先到。dict 字面量字段与 `**expr` 解包项、
  模板调用显式命名参数与 `**expr` 解包项均按书写顺序混排——「保留先到者」与源码一致

示例:
```infd
base = { a = 1, b = noexist }
merged = { **base, c = 3 }          # b 保持 noexist
list_all = [ *parts, "suffix" ]
server = Server(port = 8080, **$tuning)
server2 = Multi(*$positional_list)
```

## 2.8 模板在 list 上展开（显式轴）

> 把外部裸列表**批量构造**为模板实例（map 语义），与 `each`（只校验不构造）互补。
> 语法致敬 C++ pack expansion：`...` 全语言只有一种含义——**展开/重复**，位置决定作用域：
> 参数级 `...` = 该参数随轴变化（本调用展开）；调用级（`)` 后）`...` = **展开向外传播**，
> 把本调用的展开结果作为**包围模板调用**的轴，整个嵌套模式逐元素重复；
> 调用级（`)` 后）`^` = **笛卡尔积**（多轴全组合），与 `...` 正交可叠加（`^...`）。

基础语法:
- 参数级 `...` 后缀 = **展开轴**标记（位置/命名参数均可；与参数值来源无关——
  `$` 引用、字面量 list、模板构造 list 都能作轴）
- 有 ≥1 轴 → 调用**展开**，结果**恒为 list**；0 轴 → 普通单次调用
- 调用级（`)` 后）`...` = **展开传播**：本调用的展开结果（list）作为**包围模板调用**
  的轴继续展开——`B(A($list...)...)` ⟹ `[B(A(x)) for x]`
- 传播可链式：`C(B(A($list...)...)...)` ⟹ `[C(B(A(x))) for x]`（每层显式写 `...`）
- 调用级（`)` 后）`^` = **笛卡尔积**：各轴独立全组合、无长度约束；展开顺序
  **第一个轴最慢变化**（等于嵌套 `for` 的书写顺序，保证可审计、可预测）
- **多轴默认 zip**（等长配对）
- **后缀顺序固定**：`^`（组合模式）先、`...`（传播）后，可叠加 `^...`；
  反序 `...^` → 语法错误

```infd
nodes = Node(host = $hosts...)                   # 单轴：N 个实例
pairs = Node(host = $hosts..., port = $ports...) # 多轴 zip：等长配对
wrapped = B(A($hosts...)...)                     # 传播：整个模式逐元素重复 → [B(A(h))…]
chain = C(B(A($hosts...)...)...)                 # 链式传播：三层嵌套
all = [*Node(host = $hosts...)..., "extra"]      # 展开结果 splice 进数组
matrix = Node(host = $hosts..., port = [80, 443]...)^   # 笛卡尔积：全组合
validated: <list, each(Node)> = Node(host = $hosts...)   # 展开 + each 双保险
```

**轴与解包可叠加**（外部数据生成的关键组合）:
```infd
!file p"services.json" as json import . as services
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
- **笛卡尔积模式**（调用级 `^`）：各轴独立全组合、无长度约束；
  展开顺序**第一个轴最慢变化**（等于嵌套 `for` 的书写顺序，保证可审计、可预测）
- **单轴 + 调用级 `^`** → 合法 no-op（1 个轴无 zip/积之分）
- **零轴 + 调用级 `^`** → 报错（`template.expand_no_source`，与传播无源同码）
- **顶层 / dict 字段等非模板位置 + `^`** → 同传播 no-op：结果仍为本调用的积展开 list
- **实例总数上限** `MAX_EXPAND`（如 10000）：展开实例总数（zip 取轴长、积取乘积）超限 →
  报错（`template.expand_too_large`），防止 `$` 数据源导致产物爆炸（可审计定位）
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
| `Template($a..., $b...)^` | `^`（调用级）：笛卡尔积，N×M 次调用，首轴最慢变化 |

## 2.9 模板可变参数收集（模板配置）

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

## 2.10 本地注入（!var）

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
- **仅文件顶层可用**（模板体 / dict 字面量内不支持；模板内中间值用字段默认值表达）——
  模板定义文件（.inft）的顶层也允许 `!var`，绑定**该文件**的 `$` 命名空间（就地解析，§1.8）
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
| `!file p"path" import path as alias` | 外部文件 | 受控（§3.3） |
| `!var 值表达式 import path as alias` | 内存 / 字面量 | **无**（纯本地） |
| `!from p"path" import T as T` | 外部模板 | 受控（§3.2，模板空间） |

vs 顶层字段:
- 顶层字段 `foo = 1` → **进输出**（你要产出它）
- `!var ... as foo` → **只进 `$` 空间**（你只当它原料）；产出经 `$foo` 引用进入字段
- **数据流单向**：`$` 引用只查 `$` 空间（`!env` / `!file` / `!var` 填充）；
  **顶层字段不在 `$` 空间，不可被 `$` 引用**（引用 → `dollar.undefined` 警告取 null）。
  管道中间态必须用 `!var` 绑定才能被后续 `!var` 引用；顶层字段是**终点**（进输出），
  不能回流进管道——保证「管道 → 输出」的单向性，杜绝隐藏循环
