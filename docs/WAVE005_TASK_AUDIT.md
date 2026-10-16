# Wave005: пригодность основы для вытесняемых задач

16.10.2026. Аудит принятой базы `d7f39d7968bd5163e908abe8911ca05e960eefd2`, до изменений Wave006. Статусы: **код** — установлен статическим чтением этой базы; **проверено ранее** — сохранённое исполнение Wave005; **источник** — первичная архитектурная документация; **требование** — условие нового runtime, ещё не результат этого аудита. Строки ссылок относятся к исходникам принятой базы. Все VA/PA ниже принадлежат synthetic E2B; ROM offsets и адреса физического PDA2k здесь не используются.

Прочитаны [Wave005](../reports/WAVE_005.md), [security model](SECURITY_MODEL.md), [threat model](THREAT_MODEL.md), [E2B audit](E2B_CPU_GPIO_AUDIT.md) и унаследованный [timer/PIC contract](E2A_CONTRACT.md). **Проверено ранее:** 24 сценария / 48 boot/reset executions демонстрируют User/MMU/SVC и последовательный healthy recovery, но не scheduler. [Host oracle](../tools/smoke_security.py#L200) проверяет CPU, RAM, descriptors, инструкции и canaries независимо от UART. Этот аудит — статический разбор, не новый аппаратный или TCG PASS.

## Что можно сохранить

| Основа | Источник и адресный тип | Статус и условие повторного использования |
|---|---|---|
| ARM entry и отдельные privileged stacks | [security_entry.S:14–21](../src/arch/security_entry.S#L14), [security.ld:18–21](../link/security.ld#L18); linker VMA=PA privileged RAM | **Код.** Инициализация IRQ/SVC/ABT/UND и 8-byte stack alignment пригодны; новый IRQ wrapper должен сохранять полный task context |
| AP/domain isolation и guard | [security.rs:171–214](../src/security.rs#L171), [security.ld:26–30](../link/security.ld#L26); User VA `01000000..01004000`, backing PA `a0200000/a0201000/a0203000` | **Код / проверено ранее.** Domain0 Client, kernel/MMIO AP1, code AP2, data/stack AP3, guard descriptor zero. Нужны отдельные mappings каждой задачи |
| Bounded copy-in arithmetic | [security_policy.rs:9–19](../src/security_policy.rs#L9); User VA range, длина в bytes | **Код / проверено ранее.** Cap, overflow и весь диапазон проверяются до чтения. Allowlist одной фиксированной страницы нужно связать с kernel-owned текущей задачей |
| Проверка SVC origin/opcode | [security.rs:226–245](../src/security.rs#L226), [305–333](../src/security.rs#L305); User instruction VA → проверенный backing PA | **Код / проверено ранее.** Unknown/unaligned/unmapped PC не разыменовывается. Сохранить ARM-only RO-code ABI и проверку границ конкретной задачи |
| Завершение ошибочного User context | [security.rs:258–302](../src/security.rs#L258), [446–459](../src/security.rs#L446); exception LR/SPSR и privileged caller frame | **Код / проверено ранее.** Отделять User fault от kernel invariant violation; заменить единственный recovery caller переходом к другой Ready задаче |
| Независимое доказательство исполнения | [smoke_security.py:200–245](../tools/smoke_security.py#L200), [test-wave005.sh:5–6](../scripts/test-wave005.sh#L5) | **Проверено ранее.** Старый guest/harness сохраняются отдельной регрессией; новые счётчики/IRQ/context tests не подменяют её |

## Почему текущий frame не является контекстом задачи

**Код:** [trap macro:64–80](../src/arch/security_entry.S#L64) и [TrapFrame:218–224](../src/security.rs#L218) согласованы по 64-byte layout. Offset здесь — **byte offset внутри privileged exception frame**, не VA или PA:

| Offset | Содержимое | Значение для переключения |
|---|---|---|
| `0..48` | r0–r12, 13 слов | Сохраняются, включая caller/callee-saved registers |
| `52` | LR текущего exception mode | Это `LR_svc/abt/und`, не `LR_usr` и не универсальный resume PC |
| `56` | SPSR текущего exception mode | Сохранённый User CPSR; надо переносить в task-owned context до нового exception return |
| `60` | trap kind | Метаданные wrapper, не регистр процессора |
| отсутствует | `SP_usr`, `LR_usr` | Без них два произвольно прерываемых контекста не независимы |

**Код / вывод:** SP/LR пользователя остаются живыми в User/System bank, пока единственный контекст находится в SVC/ABT/UND. Поэтому обычный SVC round-trip не требует копировать их в Wave005 frame. Но [security_run_user:34–58](../src/arch/security_entry.S#L34) каждый запуск заново ставит User SP=`01004000`, LR=0, регистры и SPSR=`d0`; это создание нового fixture, а не продолжение остановленной задачи. Один глобальный [SECURITY_RESUME_SP](../src/security.rs#L28) хранит только trusted SVC caller. Функция [security_return_kernel:88–93](../src/arch/security_entry.S#L88) возвращает туда, а не выбирает другой User context.

**Источник:** ARM DDI0100I, [§A2.4.2, A2-6..7](https://e2e.ti.com/cfs-file/__key/communityserver-discussions-components-files/1023/ARM-Architecture.pdf#page=44): User/System разделяют registers; IRQ/SVC/ABT/UND имеют собственные r13/r14/SPSR. FIQ также переключает r8–r12. Для первого runtime FIQ остаётся masked. **Требование:** task context хранит r0–r12, User SP/LR, resume PC и saved CPSR в privileged RAM. При кратком доступе через System mode нельзя потерять исходный privileged SP, exception LR/SPSR или временные регистры; stack pointer из User не используется как kernel frame pointer.

**Источник:** [DDI0100I §A2.6.4–8, A2-20..24](https://e2e.ti.com/cfs-file/__key/communityserver-discussions-components-files/1023/ARM-Architecture.pdf#page=58): SVC возвращается по LR; IRQ — LR−4; retry prefetch abort — LR−4, data abort — LR−8. CPSR восстанавливается из SPSR. **Код:** Wave005 возвращает только успешный SVC через `movs pc,lr`; fault PC вычисляется для диагностики [security.rs:286–295](../src/security.rs#L286), fault не повторяется. **Требование:** normalize resume PC один раз по виду exception; IRQ нельзя подключить к SVC return без поправки. Прерывание продолжает User с сохранённой границы инструкций; faulted task не возобновляется.

## MMU и адресные пространства

**Код:** одна [SECURITY_L1/L2](../src/security.rs#L44) описывает одну User view. Identity aliases `[a0000000,a8000000)` и MMIO `[40000000,41000000)` доступны только privileged. Добавление второй AP3 области в ту же User view дало бы обоим приложениям доступ к обеим областям. Разные ranges в таблице задач сами по себе не создают изоляцию.

**Источник:** [DDI0100I §B4.9, B4-39](https://e2e.ti.com/cfs-file/__key/communityserver-discussions-components-files/1023/ARM-Architecture.pdf#page=739) относит ASID support к VMSAv6; [§B8.3](https://e2e.ti.com/cfs-file/__key/communityserver-discussions-components-files/1023/ARM-Architecture.pdf#page=845) при PID=0 задаёт VA=MVA. **Требование:** для этого ARMv5 эксперимента оставить PID=0, caches off и переключать kernel-owned TTBR с invalidation всех TLB entries; не рассчитывать на современные ASID, XN, DSB/ISB/SRS/RFE.

**Код / требование:** [mmu_init:192–196](../src/security.rs#L192) уже использует `MCR p15,0,...,c2,c0,0`, `c8,c7,0` и XScale cpwait (MRC TTBR, dependent MOV, branch). Для смены задач нужны отдельные L1/L2 либо обновляемая единственная current-task view с теми же privileged kernel/vectors/stacks/MMIO mappings. Table writes, TTBR, full TLBI и cpwait выполняются до возврата User и без IRQ/references, пересекающих смену адресного пространства. **Модель:** [E2B audit](E2B_CPU_GPIO_AUDIT.md#cpu-и-coprocessors-что-действительно-моделируется) закрепляет QEMU TLBIALL и отсутствие физических cache; принятый c7 maintenance NOP не доказывает реальный PXA263 ordering/cache coherence. Cache-enabled hardware switching требует отдельного SoC/errata контракта.

## IRQ, системные вызовы и время жизни

**Код:** vectors [security_entry.S:8–9](../src/arch/security_entry.S#L8) направляют IRQ в `security_fatal`; User SPSR=`d0` сохраняет I/F=1. [rust_main](../src/security.rs#L417) не настраивает timer/PIC. Следовательно, бесконечный User loop без trap удерживает CPU. Host timeout завершает тест, но не исполняет guest preemption. Это уже описанный предел [security model](SECURITY_MODEL.md#границы-подсистем) и сценарий P2 [threat model](THREAT_MODEL.md).

**Модель:** [E2B:14,261](../crosshair-emulator/qemu/crosshair-blueangel-e2b.c#L14) повторно использует E2A. [E2A:36–42](../crosshair-emulator/qemu/crosshair-blueangel-e2a.c#L36) задаёт timer PA=`40a00000`, PIC PA=`40d00000`, virtual frequency=3686400Hz, timer0 PIC source bit26. [PIC:78–87](../crosshair-emulator/qemu/crosshair-blueangel-e2a.c#L78) отделяет pending/mask/FIQ routing. [OSSR:190–196](../crosshair-emulator/qemu/crosshair-blueangel-e2a.c#L190) — W1C, OIER disable не очищает latched event; [reset:307–320](../crosshair-emulator/qemu/crosshair-blueangel-e2a.c#L307) отменяет callbacks и очищает state. Это уже доступный timer/PIC subset, изменение QEMU не нужно. **Требование:** timer IRQ проверяет source/status, подтверждает W1C, переустанавливает match, затем сохраняет/выбирает User context. Ненулевой IRQ count сам по себе не доказывает progress двух задач.

**Источник:** [DDI0100I §A2.6, A2-16](https://e2e.ti.com/cfs-file/__key/communityserver-discussions-components-files/1023/ARM-Architecture.pdf#page=54) задаёт I=1 при exception entry. **Код:** безопасность copy-in [security.rs:383–389](../src/security.rs#L383) прямо опирается на single CPU, IRQ/DMA-free bounded copy; runtime records, canaries и Rust `&mut TrapFrame` также не допускают конкурентного использования. **Требование первого runtime:** kernel/SVC/ABT/UND/IRQ исполняются с IRQ/FIQ masked; preemption разрешена только для User, I=0/F=1 при возврате. В Exit/Yield сначала фиксируются return value, полный User context и lifecycle state, затем выбирается задача. Не переключать mapping между validation и dereference. Kernel fault остаётся fatal invariant violation; User fault меняет только её kernel-owned state на Faulted.

**Код:** [init_user:144–169](../src/security.rs#L144) очищает data/stack перед каждым новым последовательным fixture. **Требование:** фиксированные task-owned pages и context records не очищаются и не переиспользуются, пока задача Ready/Running либо существует незавершённая операция с её памятью. Для Wave006 достаточен отказ от повторного выделения Exited/Faulted slots до reset: identity выбирает ядро, пользовательский номер задачи не даёт прав на чужую память.

## Проверяемый следующий рубеж

**Требование:** отдельный guest/harness должен наблюдать реальный ARM Busy Loop без Yield/SVC и одновременно рост счётчика healthy task; сохранять и проверять все general registers, User SP/LR, flags и resume PC; проверять read/write чужого backing allocation, kernel/MMIO и guard faults; подтверждать продолжение другой задачи после fault; сверять TTBR/descriptors и timer ownership; повторять через `system_reset`. Старый `scripts/test-wave005.sh` остаётся самостоятельным исполняемым подтверждением сохранённого ABI. RAM учитывается по kernel extent, privileged stacks, каждой L1/L2 и allocated User pages; unmapped guard VA и sparse flat binary gap не считаются RAM allocation. Реальный PXA263, cache timing, DMA, suspend/wake и загрузчик приложений остаются **неизвестными/вне этого прототипа**.
