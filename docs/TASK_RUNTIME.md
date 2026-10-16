# Crosshair Task Runtime 0.1

Wave006, 16.10.2026; исходная принятая база `d7f39d7968bd5163e908abe8911ca05e960eefd2`. **Реализовано:** отдельный `crosshair-tasks`, две статические User-задачи и timer preemption на неизменённой synthetic `crosshair-blueangel-e2b`/CPU260 proxy. Точный статус исполнения, image/source hashes и измерения — [Wave006](../reports/WAVE_006.md); предварительный разбор прежней основы — [Wave005 task audit](WAVE005_TASK_AUDIT.md). Здесь **код** означает установленный по исходникам контракт, **проверка** — конкретные assertions harness, **неизвестно** — свойство, не установленное этим экспериментом. Это не физическая защита PXA263 и не общий application loader.

## Разделение ответственности

| Компонент | Контракт и статус |
|---|---|
| [tasks_entry.S](../src/arch/tasks_entry.S#L38) | **Код:** ARM banked-register capture, exception-specific PC normalization и restore; 80-byte privileged stack frame |
| [context.rs](../src/task_runtime/context.rs), [mod.rs](../src/task_runtime/mod.rs#L15) | **Код:** фиксированные Context/Task schema, kernel-owned identity/state и lifetime |
| [memory.rs](../src/task_runtime/memory.rs#L85) | **Код:** две отдельные legacy L1/L2 tables, User VA→own PA, privileged aliases, TTBR/full TLBI/cpwait |
| [scheduler.rs:3–6](../src/task_runtime/scheduler.rs#L3) | **Код:** чистая round-robin policy; без MMIO, CPU mode или syscall parsing |
| [syscall.rs](../src/task_runtime/syscall.rs#L15), [security_policy.rs](../src/security_policy.rs#L9) | **Код:** SVC origin/immediate/number, bounded copy policy и lifecycle operations |
| [tasks.rs](../src/tasks.rs#L97) | **Код:** wiring timer/frames/policy/dispatch, kernel canaries и bounded diagnostic scenarios |
| [task_workloads.S](../src/arch/task_workloads.S#L50), [smoke_tasks.py](../tools/smoke_tasks.py#L200) | **Проверка:** настоящие ARM User fixtures и внешний oracle CPU/RAM/ELF, не host-модель scheduler |

В guest нет heap, Linux/CE runtime, filesystem, `.cxp` installer, Sleep, динамического ELF-loader или User UI. GPL host emulator остаётся в `crosshair-emulator/qemu`, собственный guest — MIT; модели E2A/E2B/display не заменяются. Wave005 guest и его Exit/Copy tests сохранены отдельно: [test-wave006.sh](../scripts/test-wave006.sh#L5) сначала вызывает прежнюю регрессию, затем новый runtime suite.

## Полный CPU context и banked state

**Код:** [Context](../src/task_runtime/context.rs) имеет `repr(C)`, размер80B и compile-time проверки offsets. Следующая таблица задаёт **byte offset внутри kernel-owned Context**, а не ROM offset/VA/PA:

| Offset | Поле |
|---|---|
| `0..48` | r0–r12, 13 слов |
| `52` / `56` | `SP_usr` / `LR_usr` |
| `60` | `pc`: resume PC для IRQ/SVC; fault instruction PC для abort/UNDEF |
| `64` | `psr`: сохранённый User CPSR из exception SPSR, включая flags/T/I/F/mode |
| `68` / `72` / `76` | kind / raw banked exception LR / нулевой alignment word |

**Код:** kind0=IRQ,1=UNDEF,2=SVC,3=data abort,4=prefetch abort. [Wrapper:41–67](../src/arch/tasks_entry.S#L41) маскирует IRQ/FIQ, сохраняет r0–r12 до scratch use и копирует именно User SP/LR через `STM ... ^`; `LR_irq/svc/abt/und` сохраняется отдельно. Он использует собственный IRQ/SVC/ABT/UND stack, frame80B сохраняет 8-byte stack alignment. User SP не разыменовывается ядром.

**Код:** normalized PC=raw LR−4 для IRQ, raw LR для SVC, raw LR−8 для data abort и raw LR−4 для prefetch abort. UNDEF учитывает ARM−4/Thumb−2. Поэтому SVC resume PC обозначает следующую инструкцию, IRQ PC — границу продолжения прерванного User. Для fault evidence SVC instruction PC отдельно вычисляется как resume−4/−2 в [mark_fault](../src/tasks.rs#L180). Причины и первичная ARM-документация — [аудит](WAVE005_TASK_AUDIT.md#почему-текущий-frame-не-является-контекстом-задачи).

**Код:** Rust сначала копирует exception frame в текущий Task. После завершения handler Assembly освобождает временный frame, [task_restore:78–86](../src/arch/tasks_entry.S#L78) загружает выбранные User SP/LR через `LDM ... ^`, SPSR, r0–r12 и возвращается через `movs pc,lr`. Исходный exception bank используется только как механизм return; выбранная задача не обязана быть той, которая вызвала этот exception. Kernel SP и exception SPSR не выбираются пользовательскими аргументами. FIQ постоянно masked; nested IRQ не вводятся.

## Task identity, состояния и время жизни

**Код:** [Task](../src/task_runtime/mod.rs#L15) занимает144B:64B metadata и80B Context. Первые16 слов: id, state, dispatches, preemptions, svc_count, copies, yields, exit_code, fault_kind, fault_lr, fault_psr, DFSR, DFAR, IFSR, fault_pc, fault_opcode; Context начинается с byte offset64. Kernel создаёт id1/2 и выбирает индекс текущей задачи из собственного record; SVC не принимает caller-selected identity.

| Состояние | Переходы |
|---|---|
| Ready=`0` | Инициализированная задача; scheduler может выбрать её и установить Running |
| Running=`1` | Единственный текущий User context; timer IRQ или Yield переводит в Ready, Copy возвращает в Running |
| Exited=`2` | Exit сохраняет r0 как exit status; задача больше не выбирается |
| Faulted=`3` | User fault или unsupported SVC origin сохраняет диагностику; задача больше не выбирается |

**Код:** policy сначала ищет Ready после предыдущего индекса, затем допускает прежнюю Ready задачу, если другая закончилась. При двух runnable задачах timer делит исполнение round robin. Если Ready нет, handler выбирает настоящий no-runnable Idle, `terminal_reason=2`. Это terminal privileged busy branch с отключённым timer/PIC; энергосбережение и wake не реализованы.

**Код:** `terminal_reason=1` — отдельная **диагностическая остановка по конечному test budget** [tasks.rs:151–156](../src/tasks.rs#L151). Она может сохранять Ready-задачи, отключает timer/PIC и даёт host стабильный snapshot. Это не no-runnable Idle и не production scheduling policy. Slots, tables, copy buffers и User memory после Exit/Faulted сохраняются до reset; освобождения, повторного выделения и stale-handle reuse нет. Пока нет general app authority, capabilities или динамического запуска задач.

## Раздельные адресные пространства

Все диапазоны далее half-open; адреса — **guest VA/PA synthetic E2B**, не host pointers и не безопасная карта RAM PDA2k. [memory.rs:14–24,92–120](../src/task_runtime/memory.rs#L14), [link/tasks.ld](../link/tasks.ld#L4):

| User VA | Task A backing PA | Task B backing PA | User доступ |
|---|---|---|---|
| `[01000000,01001000)` | `a0200000` | `a0300000` | AP2 RO code; разные ARM workloads |
| `[01001000,01002000)` | `a0201000` | `a0301000` | AP3 RW data |
| `[01002000,01003000)` | Не mapped | Не mapped | Guard, translation fault |
| `[01003000,01004000)` | `a0203000` | `a0303000` | AP3 RW stack, initial SP=`01004000` |

**Код:** каждая L1 ссылается на собственную L2. Только эти три страницы доступны User; та же User VA в другой задаче выбирает её собственный PA. Identity aliases RAM `[a0000000,a8000000)`, vectors и MMIO `[40000000,41000000)` имеют AP1: User denied. Это закрывает и прямое обращение к известному чужому PA через identity VA. Остальные descriptors нулевые. Domain0 Client (`DACR=1`), SCTLR=`79`, FCSE PID=0; kernel/page tables/stacks остаются общими privileged identity mappings.

**Код:** [activate/install](../src/task_runtime/memory.rs#L126) выполняются с IRQ/FIQ masked и неизменяемыми после initialization tables: drain, PID0/DACR1, новый TTBR, full unified TLBI, prefetch maintenance и XScale cpwait. User pointers/references не живут через этот переход. ARMv5 path не использует ASID или ARMv6+ barriers. Caches off и QEMU maintenance NOP ограничивают claim функциональной MMU/TLB моделью. Как в Wave005, ARMv5 не получает XN: User RW data/stack остаются executable. RO SVC-origin policy ограничивает syscall entry, но не обещает запрет instruction fetch из data.

## Таймер и граница вытеснения

**Модель / код:** timer PA=`40a00000`, PIC PA=`40d00000`, source bit26; [унаследованный contract](E2A_CONTRACT.md#timer-и-pic) и [constants](../src/tasks.rs#L15) задают3686400Hz virtual counter. `INTERVAL=36864` — **10ms в этой модели**. При IRQ ядро проверяет PIC/OSSR, очищает event W1C и ставит OSMR0=`OSCR+INTERVAL`, затем сохраняет/выбирает task и переключает MMU. Это rearm относительно времени handler; не обещается накопление пропущенных quanta, hard realtime или измеренный interrupt latency.

**Код:** User запускается ARM с CPSR low byte=`50`: I=0/F=1; весь kernel handler исполняется I=F=1. Поэтому pending timer может войти после возврата User, но не вклиниться между SVC validation/read, lifecycle update и TTBR change. SVC bounded и run-to-completion; IRQ в ядре и nested IRQ не поддерживаются. User-controlled T через BX сохраняется при IRQ, а Thumb SVC отвергается как unsupported origin и завершает только задачу. Privileged-origin exception, повреждение kernel canaries или неожиданная конфигурация IRQ/MMU — kernel invariant failure с terminal panic; это не восстанавливаемый User fault.

## Минимальный syscall ABI

**Код:** [dispatch](../src/task_runtime/syscall.rs#L15) разрешает **ARM `svc #0` из установленного собственного RO code extent**; номер=r7. Сначала проверяются state/alignment/range, затем opcode читается через свой privileged PA alias. SVC из data/stack либо Thumb origin → Faulted без разыменования непроверенного opcode. Неизвестный номер или ненулевой immediate при допустимом origin возвращает `-ENOSYS`, без privileged operation.

| r7 | Операция и аргументы | Результат |
|---|---|---|
| `0` | Exit, r0=произвольный status | Сохраняет status, Exited; в User не возвращается |
| `1` | Copy, r0=source User VA, r1=byte length | Копирует0..64B в собственный kernel diagnostic buffer задачи; r0=length либо errno |
| `2` | Yield, аргументы не используются | r0=0, Ready и выбор следующей задачи; возврат по сохранённому SVC resume PC |

**Код:** Copy сохраняет Wave005 policy [checked_copy](../src/security_policy.rs#L9): `len>64` → `-EINVAL=-22` прежде других проверок; overflow или выход за собственную data page → `-EFAULT=-14`; `-ENOSYS=-38` используется для неизвестного syscall/immediate. Ошибки представлены 32-bit two's complement. Весь диапазон проверяется до первого byte read, затем VA переводится в PA текущей задачи. Нулевая длина допустима с ptr в закрытом `[01001000,01002000]`, включая one-past-end; null/zero отвергается. Code/stack/kernel/MMIO/foreign PA pointers отвергаются этим узким ABI, даже если какой-то из них readable для иных целей. Copy не выдаёт чужие bytes и не выполняет output/file/modem/MMIO action. При обычном return сохранённые registers/flags восстанавливаются, кроме результата r0; Exit не имеет return value.

**Unsafe/FFI contract:** Assembly→Rust передаёт валидный80B frame на собственном banked stack, недоступном User, с проверяемыми bounds/alignment. Kernel — единственный CPU writer; IRQ/FIQ masked, DMA нет. `&mut Task` не пересекается с stack frame/table allocations, User bytes читаются через volatile raw pointers после проверки. `memory::activate` вызывается после завершения Copy и без borrowed User references. Privileged aliases и shared kernel не изолируют ошибки самого kernel/driver; host QMP/QTest остаётся trusted и может менять любой PA.

## Что проверяет исполняемый harness

**Код fixtures:** Task A [busy loop](../src/arch/task_workloads.S#L54) непрерывно увеличивает собственные counter/accumulator, без SVC/Yield в positive case. Task B [healthy loop](../src/arch/task_workloads.S#L147) считает отдельно, выполняет реальный Copy, сохраняет User return/CPSR и проверяет ошибочные arguments. Оба имеют разные r0–r12/LR sentinels,56B stack image и NZCV self-check при повторении loop. Это проверка выбранных значений/flags; исчерпывающая верификация ISA не заявляется.

**Проверка harness:** [smoke_tasks.py](../tools/smoke_tasks.py#L200) сверяет image hashes, actual ELF/opcodes, CPU mode/PC, kernel frames/stacks/canaries, обе L1/L2 целиком, независимые PA counters/accumulators, syscall results и отсутствие ошибок self-check. Сценарии0..7: Busy Loop; чужое чтение; чужая запись; kernel write; guard; UNDEF; Yield/Exit; Thumb SVC. Fault вводится настоящим User instruction после уже состоявшегося вытеснения, затем host требует дальнейшие B preemptions/progress. Healthy Copy также проверяет overflow/end/cap/code/null/foreign-PA/unknown-number/immediate и zero-length правила. Wave005 отдельно сохраняет ранее проверенные MMIO/CP15/code-write и prefetch tests.

Host ждёт UART лишь как повод остановить CPU, затем самостоятельно читает RAM/register snapshots. Каждый case исполняется дважды через QMP `system_reset`; перед entry host портит BSS, stacks и собственные User pages, чтобы прежний state не засчитывался как новый boot. Host не подаёт scheduler IRQ и не редактирует progress counters во время исполнения. Полный запуск: `scripts/test-wave006.sh`; только новые tests: `scripts/test-tasks.sh`. Partial `--case` имеет `complete_suite=false` и не доказывает весь suite. Полные actual JSON/logs и точные хеши закрепляются в [отчёте](../reports/WAVE_006.md).

## Учёт памяти и следующий loader

**Код / метод:** [linker](../link/tasks.ld#L15) резервирует kernel extent от `_start` до `__image_end`, включая BSS, tables, Task records, copy buffers, alignment и16KiB SVC +4KiB IRQ +4KiB ABT +4KiB UND stacks. Каждая задача добавляет L1=16384B, L2=1024B, Task=144B (включая80B Context), Copy=64B; эти bytes уже входят в kernel extent и второй раз к нему не прибавляются. Common stacks не являются per-task kernel stacks. User allocation — три mapped4KiB pages на задачу; reserved physical span содержит ещё guard hole4KiB, которое не mapped и не инициализируется guest. Оно сохраняется недоступным и не переиспользуется. Отдельно учитываются64B low vectors. [memory_accounting](../tools/smoke_tasks.py#L304) публикует эти категории по actual ELF symbols; kernel extent и mapped working bytes нужно отличать от зарезервированных spans с holes.

Flat BIN включает gaps до отдельных User PA, debug ELF содержит debug metadata; размеры файлов не равны working RAM. Окончательные extent/bytes/hash берутся из соответствующего image manifest и runtime report, а не из фиксированных чисел другого build.

**Следующий дизайн, не реализация:** настоящий app loader должен валидировать bounded image/segments и overlap, закреплять kernel-owned identity/generation и memory ownership, создавать собственные RO/RW/guard mappings, выбирать entry/stack/initial CPSR и публиковать Ready только после полной initialization. General pointers потребуют page-table-aware checked copy; teardown — доказанного отсутствия живых CPU/syscall/DMA references до reuse. App format/version/authority и подлинность payload потребуют отдельных решений; hash сам по себе не authentication. Эти требования продолжают существующие context/memory/scheduler/syscall boundaries без включения installer/filesystem/crypto в Wave006. Для физического PXA263 остаются неизвестными actual handoff/RAM reservations, caches/TLB timing/errata/DMA и timer latency; аппаратные drivers/запуск здесь не выполнены.
