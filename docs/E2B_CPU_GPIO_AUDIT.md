# E2B: аудит CPU, CP14/CP15 и GPIO PXA26x

Дата: 16.10.2026, Engineering Wave003. Boot0.1, E1, E2A и UI0.1 приняты ранее и здесь не повторяются. **Результат этой работы — проверенный по первоисточникам контракт для нового исполняемого теста**, не аппаратная валидация PXA263. Физический PDA2k не использовался.

Статусы: **источник** — документация/закреплённый код; **модель** — поведение QEMU; **решение E2B** — ограничение эксперимента; **вывод** — интерпретация источника; **неизвестно** — свойство реального экземпляра пока не установлено. Исполнение новых probes подтверждается отдельным журналом, а не этой таблицей исходников.

## Закреплённые источники

- **Q92:** [QEMU9.2 commit `ae35f033b874c627d81d51070187fbf55f0bf1a7`](https://github.com/qemu/qemu/tree/ae35f033b874c627d81d51070187fbf55f0bf1a7). Четыре локальных файла повторно сверены SHA-256 с raw-файлами этого commit; строки ниже относятся к нему.
- **K:** [PXADroid commit `3712fd6f197113f19959eba85b3628b202e30d64`](https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/), прочитаны через `git show <commit>:<path>`. Linux — исследовательский источник, runtime/драйверы в ядро не переносятся.
- **DM:** Intel *PXA26x Processor Family Developer’s Manual*, **278638-002**, оригинальные страницы на зеркалах. [GPIO §4.1](https://manualsdump.com/en/manuals/intel-pxa26x/110745/109), [CP14/MIDR §2.3](https://manualsdump.com/en/manuals/intel-pxa26x/110745/34), [MIDR table2-3](https://intel.manymanuals.com/laptops/pxa26x/user-manual-435/35). Это идентифицированное издание; полный PDF/hash здесь не закреплён, OCR зеркала не считается безошибочным.

| Файл Q92 | Сверенный SHA-256 |
|---|---|
| `target/arm/tcg/cpu32.c` | `ce85d9368effdfd53c2709374cf01dabf764dfbf63372e026c75b13e45671c66` |
| `target/arm/cpu.c` | `67628b4cfff3da8b4a02617c1d2b7a838a0e39a109ac090ef665ce706a62bb75` |
| `target/arm/helper.c` | `596bcaf237fc584d53fad51a045ef151193387201c85ab6249a1d66736df577a` |
| `target/arm/ptw.c` | `0d83eefa1df18c6cd8244057003b9b5a502d00a04b205f3e63d911f6b260557b` |

## CPU и coprocessors: что действительно моделируется

Все encoding ниже — ARM `MRC/MCR pN, opc1, Rt, cCRn, cCRm, opc2` в privileged ARM state.

| Область / encoding | Подтверждённый контракт и его предел |
|---|---|
| CPU260, MIDR `p15,0,c0,c0,0`; CTR `...,1` | **Модель:** V5+XSCALE, MIDR=`0x69052903`, CTR=`0x0d172172`, SCTLR reset=`0x78`: [Q92 cpu32.c829–838](https://github.com/qemu/qemu/blob/ae35f033b874c627d81d51070187fbf55f0bf1a7/target/arm/tcg/cpu32.c#L829). **Источник DM:** табл2-3, печатная2-5, различает PXA26x A0/B0/B1 ID=`69052903/69052d05/69052d06`. Эти stepping IDs не доказывают package263 или MIDR экземпляра. См. [профиль E2A](E2A_CPU_PROFILE.md). |
| Reset CPU/vectors | **Модель:** `cpu.c235–249` очищает reset state и сбрасывает CP registers; `365–385` устанавливает SVC, маски исключений и PC0 либо `ffff0000` при SCTLR.V. [Exception vector selection helper.c11434](https://github.com/qemu/qemu/blob/ae35f033b874c627d81d51070187fbf55f0bf1a7/target/arm/helper.c#L11434) использует SCTLR.V. Generic loader затем задаёт entry собственного ELF. Low-vector RAM и сохраняемая RAM платы — synthetic, не factory boot/reset. |
| SCTLR `p15,0,c1,c0,0` | RW reset=`78`; `helper.c9843–9862`, write path=`5457–5498`: изменение вызывает software TLB flush; часть битов не реализована. Для XSCALE отключено обычное завершение translation block ради приближения двух prefetched instructions. Readback C/I/V не доказывает cache/pipeline точность. |
| TTBR `p15,0,c2,c0,0`; DACR `p15,0,c3,c0,0`; PID/FCSE `p15,0,c13,c0,0` | RW, **модельный reset0**: `helper.c4459–4466`, `672–677`, `633–637`; FCSE/DACR writes=`402–421`. FCSE влияет на VA ниже`02000000` (`ptw.c3493–3503`). Для alias test PID должен быть0; readback PID отдельно восстановить до MMU enable. |
| MMU/TLB | Реальный functional page walk: [ptw.c1013–1065](https://github.com/qemu/qemu/blob/ae35f033b874c627d81d51070187fbf55f0bf1a7/target/arm/ptw.c#L1013) читает L1, section PA, domain/AP; AP3 разрешает RW (`927–956`). `p15,0,c8,c7,0` вызывает TLBIALL (`helper.c739–741`). Это software translation/TLB, не модель физических TLB lockdown/timing/errata. |
| Cache/write-buffer maintenance | `p15,0,c7,c10,4` drain и `p15,0,c7,c5,4` prefetch flush принимаются broad CACHEMAINT **NOP** (`helper.c690–693`). XSCALE cache lockdown c9 также **NOP**, прямо по причине отсутствия cache (`4594–4609`). Проба может проверить исполнение/readback без UNDEF, но не dirty lines, DMA coherence, ordering или реальный drain. |
| XSCALE AUXCR `p15,0,c1,c0,1`; CPAR `p15,0,c15,c1,0` | Хранимые RW registers reset0 (`helper.c4579–4593`); CPAR write masked`3fff`. Наличие этих полей не доказывает все аппаратные эффекты AUXCR/CPAR. В минимальный positive path необязательны. |
| CP14 `p14,0,c0,c0,0` | Generic **DBGDIDR RAZ**, `helper.c733–734`; регистрация для любого CPU безV7 (`8849–8863`), включая CPU260. Это не PXA PMNC. |
| CP14 clock/power/performance | В отдельной E2A composition PXA-регистры отсутствуют. Исторический [Q91 pxa2xx.c357–393](https://github.com/qemu/qemu/blob/fd1952d814da738ed107e05583b3e02ac11e88ff/hw/arm/pxa2xx.c#L357) добавлял их через SoC setup, не CPU260 init. Поэтому CLKCFG `p14,0,c6,c0,0` и PWRMODE `p14,0,c7,c0,0` ожидаются **UNDEF в нашем subset**. На настоящем PXA26x это существующие clock/power controls (DM§2.3.3, §3.7); отсутствие относится только к модели. |

**Источник:** [DM§3.4.1.2, печатная3-7](https://manualsdump.com/en/manuals/intel-pxa26x/110745/73) говорит о потере SDRAM contents при полном аппаратном reset. QEMU `system_reset` с сохранением RAM/повторной загрузкой ELF проверяет наш виртуальный reset; переносить это обещание на аппарат нельзя.

## GPIO: регистры и граница реализации

**Источник:** DM§4.1.4, табл4-30 ([печатные4-21](https://intel.manymanuals.com/laptops/pxa26x/user-manual-435/129), [4-22](https://manualsdump.com/en/manuals/intel-pxa26x/110745/130)); K `drivers/gpio/gpio-pxa.c:35–59`. Адреса — **PA**, база`0x40e00000`, 32-bit aligned registers; три банка GPIO0–31/32–63/64–89. Valid masks=`ffffffff/ffffffff/03ffffff`. Банков GPIO90+ в PXA26x нет; K `mfp-pxa2xx.c:233–250` выбирает lastGPIO89 вместо84 для PXA255.

| Регистр | Offset банка0/1/2 | Действие / reset |
|---|---|---|
| GPLR | `00/04/08` | RO sampled pin state, независимо от направления; reset read value зависит от внешнего/выходного сигнала, не обязан быть0 |
| GPDR | `0c/10/14` | RW, reset0; normal0..85: 0=input,1=output; special86..89 наоборот |
| GPSR | `18/1c/20` | WO, запись1 устанавливает latent output bit; запись0 без эффекта |
| GPCR | `24/28/2c` | WO, запись1 очищает latent output bit; запись0 без эффекта |
| GRER / GFER | `30/34/38` / `3c/40/44` | RW rising/falling enable, reset0 |
| GEDR | `48/4c/50` | Read latched edges, W1C, reset0; запись0 без эффекта |
| GAFR lower/upper | `54/58`, `5c/60`, `64/68` | RW, two bits/pin, reset0; последний valid mask=`000fffff` для GPIO80..89 |

**Источник:** GPSR/GPCR сохраняют preload при input; он проявляется при последующем output (DM§4.1.1, печатная4-1). Предзагрузка перед изменением GPDR также используется K `gpio-pxa.c:247–263`. Reset0 в WO command-register bitmap не принимается за независимое доказательство физических уровней или всех latent latches. **Решение E2B:** latch reset0 и внешние test inputs initially0 — детерминированные synthetic defaults; guest явно preload-ит нужные выходы.

**Источник:** GPIO86–89: GAFR=`01` выбирает GPIO; reset GAFR=`00` оставляет dedicated function. GPDR2 bits22–25: 0=output,1=input; при reset они dedicated outputs. Подтверждение: [DM§4.1.1](https://manualsdump.com/en/manuals/intel-pxa26x/110745/109), [табл4-8, печатная4-10](https://intel.manymanuals.com/laptops/pxa26x/user-manual-435/118), [табл4-29, печатная4-20](https://manualsdump.com/en/manuals/intel-pxa26x/110745/128); [K gpio-pxa.c122–129](https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/drivers/gpio/gpio-pxa.c#l122). Последний valid GAFR mask выведен из десяти 2-bit fields80..89; OCR reserved-range примечания зеркала противоречивы. Dedicated signal levels, pulls, pin contention и BOOT_SEL здесь **не моделируются**.

**Источник / вывод:** DM§4.1.1 допускает interrupt для input; [§4.1.2](https://manualsdump.com/en/manuals/intel-pxa26x/110745/111) исключает одновременный GPIO и alternate function. **Решение E2B:** edge latch только при GPIO-mode AND effective-input AND внешнем изменении уровня с подходящим GRER/GFER. AF gating — явная интерпретация ограниченной модели; отдельной аппаратной boolean equation в прочитанных разделах нет. Direction/AF changes сами не создают edge. Дребезг, pulse filters, sleep retention и wake не устанавливаются этим тестом.

**Источник:** [DM§4.1.3.5, печатная4-16](https://manualsdump.com/en/manuals/intel-pxa26x/110745/124) задаёт sticky GEDR и IRQ split; K `include/mach/irqs.h:34–36` задаёт **PIC source bits**, не Linux virtual IRQ: GEDR0[0]→8, GEDR0[1]→9, OR(GEDR0&~3, GEDR1, GEDR2)→10. PIC masking/routing не очищает GEDR. Отключение GRER/GFER не должно автоматически очищать уже latched GEDR; очистка — W1C.

## Минимальный исполняемый критерий E2B

1. Снять MIDR/CTR/SCTLR/TTBR/DACR/PID и DBGDIDR через CPU MRC; проверить модельные reset values, затем безопасный readback/restore TTBR/DACR/PID. Cache C/I readback и NOP maintenance отмечать только как functional register coverage.
2. В отдельном `no_std` guest зарезервировать 16KiB-aligned L1 и собственный RAM marker. Identity-map vectors, код/stack/table/RAM и нужные peripherals; section descriptor=`PA|0x00000c02` (AP3/domain0/C=B=0), DACR=`1`, PID=`0`. K `pgtable-2level-hwdef.h:19–34`, `proc-xscale.S:625–627`; Q92 page-walk выше. IRQ/FIQ masked, SCTLR M=1, остальные исходные биты сохранить, I/C/V/XP оставить0. Проверить alias VA`20000200`↔PA`a0000200`, отключить MMU и восстановить state. Marker не перекрывает ELF/stack/table по linker contract.
3. Для завершения CP15 операций использовать XScale cpwait из K `proc-xscale.S:71–75`: MRC TTBR, dependent MOV, pipeline branch. Принятые QEMU c7 NOP не выдавать за hardware synchronization. Отдельные CLKCFG/PWRMODE probes требуют собственного различимого **UNDEF** path, не общего data-abort PASS.
4. GPIO guest/QTest: preload/set/clear/direction, оба edge, GEDR W1C isolation, PIC8/9/10 и shared IRQ с несколькими pending, GPIO89 AF1/inverted direction; invalid offsets/width, reserved masks, reset. Host input injection — тестовый adapter, без claim ASIC3/физической клавиатуры.

**Остаётся неизвестным:** реальный MIDR/stepping, CP14/15 handoff и errata конкретного263; cache/TLB hardware timing и DMA coherence; RAM banks/aliases; electrical pin levels и полноценные mux/peripheral drivers, sleep/wake/reset разновидности. Указанный guest/QTest теперь выполнен: [actual image/QEMU hashes, diagnostic records и протокол](../reports/WAVE_003.md). Этот source audit сам по себе не является runtime PASS.
