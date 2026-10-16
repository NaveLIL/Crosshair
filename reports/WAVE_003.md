# Engineering Wave003: E2B и UI0.2

16.10.2026. Принятая база — `01973b66ce76ad6b5089b67b57be33d80b2c8f27`. **Реализовано и проверено:** собственный E2B GPIO90 subset, исполнение Rust CPU/MMU/GPIO probes на CPU260 proxy, интерактивный host-side UI0.2. Полный `scripts/test-wave003.sh` завершился exit0. [Полный журнал](wave003/all-tests.log), [22 успешных JSON test records и SHA-256 evidence](wave003/validation.json). Эти records содержат группы проверок, не число отдельных assertions.

PDA2k не подключался и экспериментальный код на нём не исполнялся. Flash/Radio/CID/физическая SD не использовались. В публикации собственные исходники и текстовые результаты; OEM binaries и private Git history не включены. GPL host model остаётся отдельно от MIT guest/UI.

## E2B: небольшой исполняемый результат

Новая `crosshair-blueangel-e2b` собирается отдельно на закреплённом QEMU9.2.0 `ae35f033b874c627d81d51070187fbf55f0bf1a7`. CPU — явно экспериментальный `pxa260`, MIDR=`69052903`, **не точный PXA263**. Старый E2A C source включён без изменений; UART/timer/PIC/RAM contract сохранён. [GPIO source](../crosshair-emulator/qemu/crosshair-blueangel-e2b.c), [контракт QEMU overlay](../crosshair-emulator/qemu/README.md), [первичные источники и аудит](../docs/E2B_CPU_GPIO_AUDIT.md).

GPIO по **PA`40e00000`**: три банка,90 линий, GPLR/GPDR/GPSR/GPCR/GRER/GFER/GEDR/GAFR, preload, sticky W1C edges и PIC8/9/10. GPIO86–89 используют AF1 и обратное направление GPDR. Dedicated peripheral outputs не реализованы. Только проверенные offsets и aligned32 accesses принимаются; invalid accesses не изменяют состояние.

| Фактически выполнено | Результат / evidence |
|---|---|
| QTest без исполнения гостя | Все90 direction/preload, четыре AF/pin, rising/falling, direction/AF gating, GEDR W1C isolation/shared IRQ, mask/route, реальные IRQ/FIQ/OUT/OE transitions, OE1/OUT0 на2/89, reserved masks, warm reset, invalid access diagnostics/no mutation — [PASS](../crosshair-emulator/evidence/e2b/qtest/result.json) |
| TCG positive guest, два boot в одном QEMU | Reset CP15 readback, PID restore, cache control bit readback, uncached MMU alias read/write, GPIO20/89 direction/AF/preload, masked pending затем пять IRQ, exception return, BSS poison/clear и terminal SVC idle — [PASS](../crosshair-emulator/evidence/e2b/execution/gpio-boot-reset/result.json) |
| TCG GPIO fault1/2/3 | Unsupported offset`6c`, RO GPLR write, byte GPDR read → data-abort vector, DFSR=`1008`, точный DFAR — [1](../crosshair-emulator/evidence/e2b/execution/fault-1/result.json), [2](../crosshair-emulator/evidence/e2b/execution/fault-2/result.json), [3](../crosshair-emulator/evidence/e2b/execution/fault-3/result.json) |
| TCG CP14 fault4/5 | CLKCFG/PWRMODE MRC → UNDEF; сохранённые LR/SPSR и opcodes`ee160e10/ee170e10` сверены с образом и памятью — [4](../crosshair-emulator/evidence/e2b/execution/fault-4/result.json), [5](../crosshair-emulator/evidence/e2b/execution/fault-5/result.json) |

First-edge masking проверяется самим guest при включённом CPU IRQ: GEDR0=1 и ICPR bit8 при ICMR=ICIP=0, handler count0. После guest write ICMR тот же pending доставляется. Host подаёт0↑,1↑,2↑,2↓,89↑; каждый boot завершает count5/checks`7f`/error0. Диагностика на каждом boot:

```text
CROSSHAIR E2B — GPIO READY
CROSSHAIR E2B — CP15 MMU GPIO IRQ PASS
```

[Byte-exact UART двух запусков](../crosshair-emulator/evidence/e2b/execution/gpio-boot-reset/qemu-uart.log). MMU test включает M-bit и действительно читает/пишет через VA`20000200`→PA`a0000200`; собственная16KiB L1 использует section AP3/domain0/C=B=0, затем исходные control/TTBR/DACR/PID восстановлены. Cache maintenance в QEMU — NOP; readback не доказывает физические кэши или DMA coherence. CP14 traps показывают отсутствие двух controls **в этой composition**, хотя аппаратный PXA26x имеет эти controls.

Host runtime SHA-256=`934861b3766fe0de5a7cf0ac766a12284887c01753ee0091f363d5b36ee274d2`; [build/source hashes](../crosshair-emulator/evidence/e2b/build/source.json). [Normal image manifest](../crosshair-emulator/evidence/e2b/images/normal/image.json), [negative image](../crosshair-emulator/evidence/e2b/images/negative-test/image.json), [ELF attributes](../crosshair-emulator/evidence/e2b/images/normal/elf-report.txt), [disassembly](../crosshair-emulator/evidence/e2b/images/normal/disassembly.txt). Проверены ELF32LE ARMv5TE/EABI5 soft-float, отсутствие hosted runtime/dynamic imports; flat RAM image и64B vector file остаются локальными build outputs.

## Сохранённые регрессии

| База | Повторный результат |
|---|---|
| Boot0.1 VersatilePB/ARM926 | Normal HELLO и panic HALTED: реальное исполнение, stacks/BSS/idle PASS; HaRET adapter только compile;19 parser tests PASS |
| E1 QEMU9.1 Connex/Verdex/Mainstone | Все3 TCG timer guests и3 QTest PASS; прежний `PASS_WITH_RECORDED_MODEL_LIMITATIONS`: timer state переживает reset |
| E2A QEMU9.2 | Два boot с3 IRQ/boot, четыре data-abort probes и полный QTest PASS |
| UI0.1 | Все11 исходных тестов, Cozette subset/license и прежний raw565/PNG golden сохранены |

[Новые regression records](wave003/validation.json) и общий журнал не перезаписывают принятые E1/E2A/UI0.1 evidence. Там же приведены hashes14 byte-identical baseline source files и неизменившихся E1/E2A flat RAM/vector images. ELF hashes отличаются из-за debug/build metadata; идентичность всего ELF не заявляется. E2A timer reset по-прежнему отличается от исторического E1 и не маскирует его limitation.

## UI0.2 и память

[Компоненты и input contract](../docs/UI_0.2.md): list row, button, selection, title bar и softkeys; Up/Down/Left/Right/Select/Back/Menu/TextInput; фокус доступен с клавиатуры, фильтр понимает кириллицу. Экран «Приложения» содержит16 статических диагностических entries,8 видимых строк; выбор открывает настоящий preview state, Back возвращает выбор/scroll. Это тестовые previews, не реализованные приложения телефона. Физический input driver отсутствует; тестовый adapter — FIFO8 с явным отказом при переполнении.

**Host-tested:**19 tests, включая11 принятых, и20000 fixed-seed операций clipping/stride guards/dirty coverage/failed present/event replay. [Tests log](wave003/ui/tests.log), [validation](wave003/ui/validation.json). [Сохранённая37-event последовательность](wave003/ui/ui02-input-trace.json) проходит preview/menu/softkeys/фильтр/Back и заканчивает item11 «Возврат», scroll4, invocation count3. Сохранены `target/artifacts/ui/ui02apps.png` (240×320), `.raw565` и input JSON. PNG визуально проверен; SHA-256=`766036a8f703939975fcef58b20e67cc3c4c0d82c0a21a1986b35aea22c877ae`. Генератор и проверки PNG прошли; исходный UI0.1 PNG hash не изменился.

**Реализовано, но ARM execution не проверено:** `crosshair-ui`0.2 собран для ARMv5TE, code objects/ABI проверены. UI выполнялся на host; ни LCD в QEMU, ни физический ATI display этим не проверены. `no_std`, `forbid(unsafe_code)`, отсутствие обязательного heap сохранены. Изменение состояния пока перерисовывает полный кадр; dirty machinery ограничена8 регионами, но incremental widget redraw ещё не реализован.

| RAM measurement | Принятая база | Wave003 | Разница |
|---|---:|---:|---:|
| Full RGB565 framebuffer |153600B|153600B|0B|
| UI ARM Surface handle |88B|88B|0B|
| UI state + FIFO |0B|76+36=112B|+112B|
| Guest extent entry..image_end, stacks included | E2A21672B | E2B69632B |+47960B|

UI layouts считаны из реальных host/ARM readonly object sections: [измерения](wave003/ui/memory-layout.json), [ARM dump](wave003/ui/layout-arm.txt). Font bitmap2119B и codepoints652B read-only не изменились. E2B включает16KiB L1 с16KiB alignment,116B diagnostic record, alignment gaps и прежние20KiB stacks; это footprint тестового гостя, не требование постоянно добавлять48KiB к будущему ядру. Отдельные64B vectors одинакового размера. UI state+queue — persistent budget; peak stack/время отрисовки на ARM не измерены.

## Подтверждение и открытые свойства

**Подтверждено источниками:** PXA26x GPIO0..89, AF1/инверсия86..89, карта регистров, interrupt split8/9/10; семейные stepping IDs не определяют package263. Полный CP14/15 audit с pinned commits и ограничениями OCR/PDF — в source audit.

**Исследовательская интерпретация:** edge gating требует GPIO-mode AND input direction AND external transition; отдельная аппаратная boolean equation в прочитанных разделах не найдена. QTest доказывает реализацию этого выбранного контракта.

**Synthetic choices:**128MiB contiguous RAM, low-vector scratch, FFUART test console, latch reset0/initial external0 и warm retention RAM/input wires. Реальный FFUART Blue Angel связан с модемом. QEMU reset не обещает сохранение WM RAM; Intel manual отдельно предупреждает о потере SDRAM при full reset.

**Неизвестно:** MIDR/stepping/errata конкретного263, CP14/15 HaRET handoff, cache/TLB timing/locking/coherence, реальные RAM aliases/reservations, dedicated pin outputs/pulls/contention/sleep/wake. Их нельзя считать аппаратно проверенными по CPU260 guest. LCD/GSM/SDIO/Wi-Fi/audio не добавлены.

Следующий законченный шаг — W3200 memory/stride/format/transfer contract и bounded display backend через текущий present callback; затем отдельный emulator display test. ASIC3/QWERTY и TSC2200 input contracts исследуются отдельно, M1/QwertyKey.dll остаётся приоритетным ROM artifact. Без физических измерений E2B не объявляется точным эмулятором PDA2k.

## Воспроизведение

После закреплённых bootstrap из [BUILDING.md](../BUILDING.md):

```sh
scripts/bootstrap-qemu-e2b.sh
scripts/test-wave003.sh
# Короткие отдельные циклы:
scripts/test-e2b.sh
scripts/test-ui.sh
```

Полный набор реально выполнен на macOS x86_64 с четырьмя отдельными QEMU runtimes и nightly-2025-03-01; WSL2 rerun здесь не заявляется. Команды экспорта text evidence приведены в BUILDING. Собственные ELF/raw565/PNG сохраняются локально; производительских образов для этих тестов не требуется.
