# Wave006 — Preemptive Task Runtime 0.1

16.10.2026. Принятая база `d7f39d7968bd5163e908abe8911ca05e960eefd2`. **Реализовано и проверено в ARM TCG:** две независимые User-задачи с отдельными адресными пространствами, аппаратным timer IRQ и round-robin переключением полных контекстов. Busy Loop без SVC не останавливает Healthy User; ошибка первой задачи оставляет вторую исполняющейся. Это эксперимент неизменённой synthetic E2B/CPU260 модели, не проверка защиты физического PXA263.

Фактическая команда `scripts/test-wave006.sh` завершилась **exit 0**: сохранённая цепочка Boot/E1/E2A/E2B/UI/Wave004/Wave005 и **8 новых сценариев / 16 ARM TCG executions** с повторной загрузкой каждого через QMP `system_reset`. [Полный журнал](wave006/all-tests.log), [новый suite](wave006/tasks/result.json), [проверка происхождения и свежести](wave006/validation.json). Физический PDA2k не использовался.

## Аудит и устройство runtime

[Предварительный аудит Wave005](../docs/WAVE005_TASK_AUDIT.md) установил: прежний64B trap frame не сохранял User SP/LR; SPSR=`d0` оставлял IRQ masked; IRQ vector был fatal. Работали последовательные контексты с возвратом в trusted caller, без scheduler. Эти исходники, модель E2B и проверенный security suite сохранены отдельной регрессией. **Статический вывод:** frame/return нужно расширить; прежние Client-domain/AP mappings, checked-copy policy, physical ELF loader и timer/PIC contract пригодны для повторного использования. Первичные ARM/XScale источники и точные исходные строки указаны в аудите.

Новый guest `crosshair-tasks`, feature `tasks-test`: [entry/return Assembly](../src/arch/tasks_entry.S), [Context и Task](../src/task_runtime/mod.rs), [MMU](../src/task_runtime/memory.rs), [чистая scheduling policy](../src/task_runtime/scheduler.rs), [syscall validation](../src/task_runtime/syscall.rs), [платформенное wiring и evidence](../src/tasks.rs). [TASK_RUNTIME.md](../docs/TASK_RUNTIME.md) задаёт полный ABI, unsafe/FFI contract и дальнейшую границу loader. Никакого heap, Linux runtime, динамического ELF-loader, `.cxp`, файловой системы, crypto или переноса UI в User Mode не добавлено. GPL host / MIT guest остаются раздельными.

**Реализовано:** kernel-owned id1/2, состояния Ready/Running/Exited/Faulted,80B Context с r0–r12, User SP/LR, resume PC, SPSR, raw exception LR и kind; Task144B вместе с metadata. Отдельные banked SVC/IRQ/ABT/UND stacks и80B aligned exception frames. IRQ PC=`LR_irq−4`, SVC PC=следующая инструкция; data abort=`LR_abt−8`, prefetch=`LR_abt−4`, UNDEF учитывает ARM/Thumb. После копирования frame в Task Assembly освобождает frame и восстанавливает выбранный User bank/SPSR/registers через exception return.

**Реализовано и проверено:** IRQ/FIQ masked во всех kernel handlers, User ARM low CPSR=`50` (IRQ enabled/FIQ disabled); nested IRQ нет. SVC выполняется до завершения, Copy не оставляет User reference или validation/read через переключение MMU. После каждого dispatch — новый TTBR, полный unified TLBI и ARMv5/XScale synchronization при caches off/PID0. Исправлена найденная независимым статическим review ошибка: User-controlled Thumb state теперь не попадает в kernel assert; unsupported Thumb SVC завершает только свою задачу, что отдельно исполняется case7.

## Реальная изоляция памяти

Все адреса таблицы — **guest VA/PA**, half-open, не адреса для обращения к реальному PDA2k. Источник: [memory.rs](../src/task_runtime/memory.rs), [linker](../link/tasks.ld), внешняя проверка обеих L1/L2 целиком в [smoke_tasks.py](../tools/smoke_tasks.py).

| User VA | Task A backing PA | Task B backing PA | User доступ |
|---|---|---|---|
| `[01000000,01001000)` | `a0200000` | `a0300000` | RO code, AP2 во всех1KiB subpages |
| `[01001000,01002000)` | `a0201000` | `a0301000` | RW data, AP3 |
| `[01002000,01003000)` | Нет mapping | Нет mapping | Guard |
| `[01003000,01004000)` | `a0203000` | `a0303000` | RW stack, AP3 |

Две задачи используют **одинаковые VA с разными PA и разными L1/L2**. Это не две одновременно доступные User RW области. RAM identity aliases `[a0000000,a8000000)`, vectors и MMIO `[40000000,41000000)` имеют AP1: privileged RW/User denied. Прочие descriptors нулевые; domain0 Client, DACR=`1`, SCTLR=`79`, PID=`0`. Внешний harness проверяет все4096+256 descriptors каждой задачи и разные физические code bytes. Tables, Task slots и User pages после Exit/Faulted остаются выделенными до reset; повторного использования нет.

**Ограничение ARMv5:** RW data/stack могут исполняться, современного XN нет. Раздельные RO code/RW data полезны, но не дают W^X. Только установленный RO ARM code extent допускается как syscall origin; Thumb/data/stack SVC origin завершает задачу. Host/QMP/loader и privileged kernel/drivers входят в TCB, MMU не ограничивает их и не даёт DMA isolation.

## Аппаратное вытеснение и внешний oracle

Timer/PIC — прежняя модель: timer PA=`40a00000`, PIC PA=`40d00000`, IRQ bit26, counter3686400Hz. Compare interval36864 задаёт10ms **virtual model time**, rearm от текущего OSCR в handler. Ядро ACK OSSR W1C перед rearm/return. Это не измерение latency, fairness deadline или realtime гарантии на PXA263.

[Task A](../src/arch/task_workloads.S) вычисляет собственные counter/accumulator и бесконечно возвращается в busy loop; в фактических инструкциях диапазона `task_a_busy..task_a_busy_end` нет SVC/BL. В positive case kernel не подаёт fault command, A не вызывает ни одного syscall. Task B — другой ARM workload с собственными счётчиками, настоящим Copy SVC и сохранением его возврата/CPSR. Оба проверяют r0–r12/User LR и NZCV при каждом loop, в вычислительной части используют56B User stack image с разными sentinels.

[Harness](../tools/smoke_tasks.py) запускает **TCG**, QTest использует только для physical RAM/MMIO observations и подготовки до entry. Он не инжектирует scheduler IRQ и не увеличивает progress counters. UART `PREEMPTION COMPLETE` — повод остановить CPU, не verdict PASS. Проверяются actual CPU mode/PC/SP, инструкции из hashed ELF/RAM, saved contexts, User stack/register sentinels, flags self-check, математическая связь counter/accumulator с допустимым незавершённым store, syscall stores, tables, guard/code/kernel/copy/remote RAM и timer/PIC state.

Дополнительно host останавливает реально работающий guest **до terminal budget**, сохраняет CPU registers и physical User counters, затем продолжает CPU и требует прироста. В fault cases snapshot уже видит A=Faulted; в конце A counter обязан остаться прежним, B counter — увеличиться. Отдельный B counter-at-fault из kernel evidence также сравнивается с final physical RAM. Полные snapshots остаются в case JSON.

Например, [case0 boot1](wave006/tasks/case-00/result.json): после двух IRQ host прочитал A=`191984`, B=`191`; после продолжения — A=`1053741`, B=`1387`, всего6 timer preemptions на каждую задачу, A SVC count=`0`. [Case1 boot1](wave006/tasks/case-01/result.json): User LDR чужого identity alias VA=`a0301000` дал data abort, DFSR=`d`; после snapshot A=`329186` остался неизменным, B вырос `431→2187`. Конкретные счётчики зависят от timing TCG и host observation; oracle проверяет отношения/состояния, а не эти фиксированные числа.

| Case | Фактическое ARM действие и независимая проверка |
|---|---|
| 0 | Два infinite workloads;12 timer IRQ,6 A/6 B, A без SVC, оба physical counters растут после checkpoint |
| 1 | A LDR чужого data PA через identity VA`a0301000`: section permission fault`d`; B продолжает |
| 2 | A STR в чужой sentinel по VA`a0301200`: permission fault`d`; B canary не меняется |
| 3 | A STR в privileged `TASK_CANARY` VA: permission fault`d`; actual kernel canaries сохранены |
| 4 | A LDR guard VA`01002000`: small-page translation fault`7`; физический guard poison не тронут |
| 5 | A ARM UDF opcode`e7f000f0`: настоящий UNDEF, правильный bank/SPSR/PC; B продолжает |
| 6 | Реальные Yield/Exit: A получает Yield return0, сохраняет marker`66`, Exit42; B Exit43; обе Exited, no-runnable Idle |
| 7 | A исполняет Thumb SVC`df00` из RW data VA`01001240`: User CPSR low`70`, policy Faulted, B продолжает |

Каждый из8 cases прошёл дважды в одном QEMU process через `system_reset`. Перед каждой загрузкой испорчены BSS, stacks и User data/stack, восстановлены guard/remote sentinels; ELF loader/reset вновь задаёт entry. Поэтому старый RAM snapshot не может сам дать PASS. Baseline/fault cases останавливаются по конечному diagnostic budget с Ready survivors; это **не** no-runnable Idle. Настоящий Idle case6 проверяется отдельно. Fault cases сохраняют A после2 вытеснений и дают B ещё8 timer ticks после fault.

## Системный ABI и сохранённые регрессии

ARM `svc #0`, номер r7: `0=Exit(r0=status)`, `1=Copy(r0=User data pointer,r1=length)`, `2=Yield()→r0=0`. Copy — диагностический copy-in максимум64B в отдельный kernel buffer вызывающей задачи. Сохраняется [прежняя checked_copy policy](../src/security_policy.rs): cap first, checked-add, полный диапазон до первого read; zero-length разрешён только в закрытом data start..end. Ошибки `-EINVAL=-22`, `-EFAULT=-14`, `-ENOSYS=-38`; неизвестный номер/immediate возвращают ошибку без privileged operation. r0 — результат, остальные User registers/flags восстанавливаются. Sleep не реализован.

Task B реально проверил Copy15→15, end/overflow/cap/code/null-zero/foreign-PA pointers, неизвестный номер, неверный immediate и end+zero length. Actual User CPSR после SVC=`60000050`; ответы прочитаны из physical RAM, а Copy bytes — из task-specific kernel buffer. Новая task boundary дополняет прежнюю Security Foundation, не заменяет её.

Полный [журнал](wave006/all-tests.log) содержит Boot normal/panic, compile-only Blue Angel adapter и19 parser tests; E1 три TCG+три QTest; E2A boot/reset+четыре faults+QTest; UI24 host tests/20000 deterministic operations/ARM compile; E2B boot/reset+пять faults+QTest; Wave004 три ARM boots,101 event,23 exact guest/host/QEMU framebuffer comparisons, display/input QTest и missing-reference negative regression; Wave00524 cases/48 boots и2 checked-copy policy host tests. E1 сохраняет `PASS_WITH_RECORDED_MODEL_LIMITATIONS`: историческая timer state reset limitation не скрыта. Криптографический compile-only probe Wave005 не запускался заново; его прежние evidence не выдаются за новый runtime test.

Collector сверил **63 прежних source files и18 flat outputs** с принятой Wave005 evidence: unchanged. Неизменность модели проверена отдельно. Публичные старые reports не перезаписывались. Сборка нового guest оставляет один безвредный `dead_code` warning для дублирующей data-end constant; это зафиксировано в журнале, execution checks завершились успешно.

## Память и артефакты

**Измерено по linked ELF symbols/segments и reservations**: [manifest](wave006/image/image.json), [ELF report](wave006/image/elf-report.txt), [machine code](wave006/image/disassembly.txt), [llvm-size](wave006/image/size.txt), [RAM breakdown](wave006/tasks/result.json). Guest ELF32LE ARMv5TE/EABI5/soft-float, без dynamic loader, undefined imports, allocator или Linux runtime.

| Категория | Bytes |
|---|---:|
| Kernel extent PA`_start..__image_end`, включая alignment | **80480** |
| BSS внутри kernel extent |35424|
| SVC / IRQ / ABT / UND stacks внутри extent |16384 /4096 /4096 /4096|
| Две L1 / две L2 внутри BSS |32768 /2048|
| Task table:2×144B, Context80B включён в каждую запись |288|
| Два диагностических Copy buffers внутри BSS |128|
| User A code / B code bytes в ELF |456 /476|
| User code/data/stack reservations:2×3×4096 |24576|
| Отдельные low vectors |64|
| **Kernel + mapped User pages + vectors** | **105120** |
| Guard holes:2×4096, не mapped/не инициализируются guest |8192|
| **Reserved spans с guard holes**, без промежутков между отдельными PA regions | **113312** |
| Flat BIN на диске с gaps между load segments |3113436|
| Debug ELF на диске |1187376|

**Накладные расходы одной статической задачи:** L1=16384 + L2=1024 + Task=144 (включая Context80) + Copy buffer64 = **17616B kernel allocations**; с тремя User pages — **29904B**. В kernel extent эти kernel allocations уже посчитаны; повторно к80480B их не прибавляем. Common privileged stacks28KiB не являются per-task stacks. Guard резервирует недоступный диапазон4KiB, не требует mapped backing page; host poison там — test instrumentation. `llvm-size` text5640/bss64096 и flat BIN не равны рабочей RAM. Значения характеризуют этот диагностический guest, не универсальный process manager и не high-water mark всех будущих kernel stacks.

Flat SHA-256=`a099bf581c3cb85ed9b25d3926250643deeed5d8818ec125b7c742527d40becb`; ELF SHA-256=`9fd5faf486b7acd6308c09768c8ae87f9a85135340c4960f905add7c10019eba`. Runtime QEMU SHA-256=`934861b3766fe0de5a7cf0ac766a12284887c01753ee0091f363d5b36ee274d2`. [Validation](wave006/validation.json) связывает tested sources, machine model, runtime/image bytes, full-suite log и очищенные текстовые результаты; hashes не являются authentication/secure boot.

## Воспроизведение и границы

Использовать закреплённые Rust/QEMU dependencies по [BUILDING.md](../BUILDING.md), существующие E2B и остальные cache overrides из прежних waves:

```sh
mkdir -p target/artifacts/wave006
set -o pipefail
scripts/test-wave006.sh 2>&1 | tee target/artifacts/wave006/all-tests.log
# Только новый guest/suite:
scripts/test-tasks.sh
# После полного прогона, с all-tests.log и путями к существующим tools:
python3 tools/collect_wave006_evidence.py --help
```

Фактический host: macOS x86_64, `nightly-2025-03-01`/rustc1.87.0-nightly, LLVM20.1, QEMU9.2 E2B CPU260 proxy; Linux/WSL2 не исполнялись. Full ELF/BIN, QMP/QTest protocols и исходные logs находятся локально в ignored `target/artifacts/tasks/`, `target/artifacts/tasks-tests/`, `target/artifacts/wave006/`; в reports скопированы только normalized text evidence, raw protocols закреплены hash/length. `--check-only` проверяет freshness без записи; partial task cases не подходят collector.

**Остаётся неизвестным:** физические PXA263 handoff/RAM reservations, cache/TLB/errata/DMA behavior и timer latency. Нет динамических task creation/teardown, owner-bound handles/capabilities, generalized checked copy/recoverable copy faults, priorities, kernel preemption, Sleep/wakeup или loader. Privileged fault — terminal invariant failure, не обещанное восстановление ошибочного kernel. Камера добавлена отдельной VGA-подсистемой в [HARDWARE](../HARDWARE.md) и [ROADMAP](../ROADMAP.md) по первичному руководству; sensor/interface/power/registers остаются неизвестными, драйвер не создавался.

Дополнение владельца во время завершения Wave006: утверждённый художественный UI reference сохранён для **следующего функционального Crosshair Shell0.1**, см. [UI Design System](../docs/UI_DESIGN_SYSTEM.md). Графический движок этой волной не переписывался; картинка не засчитывается за исполненную оболочку или работающие telephone/network services.

**Один следующий шаг:** создать функциональный Crosshair Shell0.1 на существующем графическом движке — Desktop с app grid, отдельный Today и проверяемая клавиатурная/touch-навигация по утверждённому reference; UI privilege boundary расширять отдельным contract. Переход от trusted fixtures к настоящему app loader после этого продолжает изолированные context/memory/policy/syscall interfaces из TASK_RUNTIME, без аппаратных процедур в рамках Wave006.
