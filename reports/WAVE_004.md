# Wave004: First Integrated Display / UI Design System0.1

16.10.2026. База — `main b1f3323a39322886650d370be948eb291c904d98`. **Реализовано и проверено:** существующий `crosshair-ui` исполняется внутри собственного ARMv5TE guest, обрабатывает логические события и показывает framebuffer240×320 RGB565 через реальную графическую консоль QEMU. Это synthetic/test-only backend, **не ATI W3200**. Физический PDA2k не использовался; ROM/Radio/Flash/SD не изменялись.

Полный `scripts/test-wave004.sh` завершился **exit0**. [Общий журнал](wave004/all-tests.log), [49 текстовых evidence files, статусы и hashes](wave004/validation.json). Прежние Boot/E1/E2A/E2B/UI reports сохранены; новый код не заменяет их архитектуру.

## Исполненный путь

Новая `crosshair-blueangel-display-test` собрана на закреплённом QEMU9.2 `ae35f033b874c627d81d51070187fbf55f0bf1a7` в отдельном cache. GPL translation unit включает неизменённый E2B, который включает E2A; старые машины и их caches сохранены. [Host model/contract](../crosshair-emulator/qemu/README.md), [build evidence](wave004/build/source.json).

Собственный [MIT guest](../src/display_test.rs) использует прежний ARM entry/vector/stack код E2B и напрямую связывает UI path dependency. Единственный `AppsScreen::render` используется и host fixture, и гостем. Обязательных `std`, `alloc`, allocator, Linux/CE runtime или второй guest framebuffer нет. MMU/cache выключены, IRQ/FIQ masked; CP15 MIDR=`69052903`, SCTLR=`78`. Это CPU260 proxy, не аппаратно точный PXA263.

Гостевые пиксели находятся в собственном статическом RAM allocation, окружённом двумя64B guards. `Surface` получает только153600B pixel slice. `present` передаёт текущий буфер синхронно; dirty rectangle проверяется по границам, после успеха очередь dirty пуста. Публикация использует пустой ARM asm memory clobber перед volatile PRESENT: это compiler ordering для данного cache-off TCG контракта, не физический DMA/cache barrier. Потребность в реальном cache maintenance этим не закрыта.

### Отдельные синтетические каналы

Все адреса ниже — **test-only PA**, выбранные для эксперимента и не полученные из ATI programming manual. Поддерживаются только aligned32 accesses; invalid offsets/width/direction/value возвращают MEMTX_ERROR без частичного изменения состояния.

| Device / PA | Offset | Контракт |
|---|---|---|
| Display `10000000` | `00` | FB_BASE RW: aligned2, полные153600B внутри обычной RAM `[a0000000,a8000000)` |
| Display | `04/08/0c/10` | RO width240 / height320 / stride480 bytes / format`565` |
| Display | `14` | Read generation; write1 синхронно копирует guest framebuffer в QEMU console и увеличивает generation; unconfigured base/другие значения отвергаются |
| Logical input `10001000` | `00/04/08` | COUNT RO / EVENT read-pop / INJECT WO |
| Logical input | `0c/10` | CAPACITY RO8 / REJECTED RO saturating counter |

Input word: tag1..8 в bits31..24 = Up/Down/Left/Right/Select/Back/Menu/TextInput; low24=0 для действий либо Unicode scalar для текста. Invalid scalar/tag/payload и full FIFO отвергаются с observable rejection, queued events не перезаписываются. Interrupts, scan codes, ASIC3/TSC2200 и аппаратные Shift/Fn/layout здесь не эмулируются. Guest последовательно переносит события через существующую UI FIFO8. Контракт будущих драйверов и semantic intents — [UI_NAVIGATION](../docs/UI_NAVIGATION.md).

PRESENT делает одну полную копию в **host console surface**; это расход памяти процесса QEMU, а не дополнительный буфер ядра. Автоматического scanout, vsync/tearing, DMA, transfer timing, backlight/panel power и sleep/wake нет. Непоказанные изменения RAM остаются невидимы до следующего PRESENT. Reset очищает base/generation/console и input FIFO; RAM-retention остаётся synthetic contract E2B.

## Реальные испытания

| Группа | Выполнено и проверено |
|---|---|
| ARM TCG canonical | Fresh boot,37 общих событий; все37 публичных состояний сверены с host,12 кадров сравниваются целиком |
| ARM TCG burst | После system_reset те же37 событий пакетами до8; ninth/full и invalid-scalar injections отвергнуты; финальный framebuffer равен последовательному replay;3 кадра сравниваются |
| ARM TCG boundary | Третий boot,27 событий: Up, Ё, erase, Й/Ъ/Ь, empty results,16-character filter, игнорирование17-го символа, Menu/Back;8 кадров сравниваются |
| Memory/CPU | На каждом checkpoint guards/sentinel/remote RAM/stack lower guard целы; BSS заранее испорчена A5 и реально очищена entry; SP/alignment/mode/PC проверены; event/frame counts и dirty clear совпадают |
| Display/Input QTest | Все65536 RGB565 values в actual QEMU PPM, synchronous publication, скрытость unpresented writes, RAM end bounds, strict MMIO/no mutation, FIFO/wrap/Unicode/backpressure, reset/republish |
| Harness negative regression | Отсутствующий обязательный host capture вызывает FAIL до запуска QEMU; старые screenshots не дают PASS; [результат](wave004/missing-reference-check.json) |

[TCG record](wave004/execution/result.json), [QTest record](wave004/qtest/result.json), [UART](wave004/execution/qemu-uart.log). Всего **101 обработанное событие,3 boot и23 точных сравнения**. Во всех23 сохранены raw565 из гостевой RAM, PNG из этих bytes и настоящий QMP screendump `.ppm`; decoded host PNG, decoded guest PNG и QEMU RGB888 сравниваются по всем76800 пикселям. **Различающихся пикселей:0** на обоих путях; raw565 также совпадает byte-for-byte. Наличие каждого объявленного host frame и manifest hash проверяется до исполнения; прежние snapshots удаляются из test output.

После каждого показа guest публикует diagnostic record; каждое отдельное событие в burst сначала помечает snapshot неготовым, а STAGE=2 записывается последним. Harness ждёт event count и останавливает vCPU для чтения. Наблюдение record не заменяет фактическую проверку framebuffer и QEMU console.

Гостевой [ELF manifest](wave004/image/image.json), [ARM attributes](wave004/image/elf-report.txt), [disassembly](wave004/image/disassembly.txt): ELF32LE/ARMv5TE/EABI5/soft-float, нет dynamic loader/imports/undefined symbols. Runtime QEMU SHA-256=`67e4b486b1813d46e7c2e5a99e0559c0e9c6b496e363dab655ee8efa50396c13`. Native Cocoa compiled, но интерактивный Cocoa-сеанс не тестировался: реальные screen tests выполнены headless через QMP.

## UI standard и эталон

Созданы [UI_DESIGN_SYSTEM.md](../docs/UI_DESIGN_SYSTEM.md), [UI_NAVIGATION.md](../docs/UI_NAVIGATION.md), [UI_SCREENS.md](../docs/UI_SCREENS.md). [Центральная тема](../ui/src/theme.rs) задаёт точные RGB565 roles, icon aliases и integer geometry; прежние компоненты используют эти tokens. Нет нового GUI framework, window manager или обязательного heap. Будущие Home/Today, File Manager, Settings, Phone/Messages и Terminal описаны как **спецификации**, не реализованные приложения. Disabled/pressed/warning/error roles и размеры будущих controls не означают существование всех этих widgets.

Эталон «Приложения»: system strip16px, app header28px, search20px,8 list rows24px с pitch26, нижние softkeys24px, видимый2px focus и настоящий scrollbar. Выбор/прокрутка, menu, previews, кириллический фильтр и Back сохраняют существующую state machine. Каталог — прежние16 диагностических entries; сеть, батарея, часы, SMS и приложения не выдумываются. Reference image не был прикреплён: оформление основано на текстовом gray-blue направлении и прежней палитре.

**24 host tests PASS**:11 исходных primitive +13 component/theme/state tests;20000 детерминированных drawing/event операций. Проверены clipping/stride guards/dirty coverage, failed-present retention, focus/softkeys, queue overflow, long labels, Ё/Й/Ъ/Ь, реальные bitmap строки даты/времени и active/disabled ink masks. [Журнал](wave004/ui/tests.log), [UI validation](wave004/ui/validation.json). Все glyph bytes, Cozette MIT notice/provenance и старый primitive golden сохранены.

Прежний Apps pixel golden сознательно изменён темой: `10739668449275078947`→`6602604234790396534`; исходный37-event trace byte-identical, SHA-256=`4eda390806a0b35041730f7448c8bd1ef8dae282ced8a90c616179b40638e2c5`. [Trace](wave004/ui/ui02-input-trace.json), [boundary trace](wave004/ui/boundary-trace.json), [12 capture descriptions](wave004/ui/frames.json), [8 boundary descriptions](wave004/ui/boundary-frames.json).

Эталон реально исполненного ARM screen сохранён как `target/artifacts/display-test/execution/canonical-37.png` и `.raw565`,240×320. PNG SHA-256=`49d7ae35ee3e210366f02583083971038079426ef189d4de49f3a8c1119a0fac`; raw565 SHA-256=`bf65c1f0283ba2203ff5a7b291a9d092600181605c57df021ef8e8db42e9f5b2`. PNG визуально проверен; actual QEMU console RGB hash и pixel-diff находятся в TCG record. Это screenshot виртуального гостя, не физического HTC.

## RAM и образ

| Измерение финальной сборки | Bytes |
|---|---:|
| Один RGB565 framebuffer |153600|
| FB prefix/suffix guards |128|
| Diagnostic record / отдельный sentinel |128 /256|
| SVC / IRQ stacks |16384 /4096|
| Lower stack guard |64|
| ARM AppsScreen / FIFO / Surface |76 /36 /88|
| Flat RAM image (text/readonly, без vectors/BSS) |20627|
| Low vectors отдельным файлом |64|
| ELF с debug information на диске |1198352|
| RAM extent entry..image_end, включая stack/guards/BSS |**195288**|

Размеры ARM objects проверены и compile-only probe, и самим исполняемым guest; [memory-layout](wave004/ui/memory-layout.json), [link/size report](wave004/image/size.txt). Apps+queue+Surface=200B находятся в зарезервированном стеке и **не добавляются повторно** к RAM extent. Шрифт по-прежнему163 glyphs:2119B rows+652B codepoints в readonly storage. Theme не добавляет mutable owner. В сравнении с E2B extent69632B новый отдельный test guest занимает на125656B больше; это разные diagnostics, а не чистая стоимость одного driver.

В предзаполненном SVC stack после каждого сценария изменён диапазон1164B. Это **observed modified span**, не доказанный peak-SP/stack bound для всех путей. Lower guard остался целым, наблюдаемые SP уложились в16KiB. Rendering time/energy на физическом ARM не измерялись. Динамические allocations для UI/guest не требуются.

## Сохранённые результаты и аппаратные неизвестные

Полный прогон повторил Boot normal/panic, compile-only HaRET и19 parser tests; E1 три TCG+три QTest; E2A boot/reset+четыре faults+QTest; E2B boot/reset+пять faults+QTest. E1 по-прежнему `PASS_WITH_RECORDED_MODEL_LIMITATIONS` из-за timer reset. Старые E1/E2A/E2B flat RAM/vector hashes и19 implementation files не изменились; ELF hashes с debug metadata не обязаны совпадать. Новые regression records перечислены в validation; старые presentation copies не перезаписаны.

**Подтверждено источниками:** [W3200 spec](../docs/ATI_W3200_SPEC.md) и [9-file source manifest](../research/w3200-sources.json) фиксируют исторический CS2/register map, remapping internal384KiB, external4MiB board data, RGB565/pitch480 и варианты панелей. Это анализ закреплённого Linux/HaRET кода, не проверенный silicon datasheet или драйвер.

**Исследовательский вывод:** framebuffer PA`08800000` выводится для конкретного historical mode/remap path; он не является измеренным адресом текущего WM framebuffer. **Неизвестно:** реальный chip/panel/stepping, cold-init и безопасное питание, active mapping/pitch/orientation/byte swapping при WM/HaRET handoff, DMA/cache coherence и аппаратный input. **Не реализовано:** настоящий ATI backend, scanout/power model, TSC2200/ASIC3 drivers и будущие системные приложения.

Следующий небольшой рубеж — read-only metadata handoff contract с fixture validation (chip/panel, PA/range, signed stride, format/orientation/state), затем отдельное решение о настоящем ATI backend и лицензиях переноса. Нельзя автоматически превратить текущие synthetic registers в ATI addresses. Физические испытания по-прежнему требуют отдельной подтверждённой процедуры.

## Воспроизведение

После подготовки закреплённых Rust/QEMU dependencies из [BUILDING.md](../BUILDING.md):

```sh
scripts/bootstrap-qemu-display-test.sh
scripts/test-wave004.sh
# Короткий цикл из чистых outputs:
scripts/test-ui.sh
scripts/test-display.sh
```

Фактический host — macOS x86_64, пять отдельных QEMU caches. Linux/WSL2 предусмотрен bootstrap, но в этой волне не исполнялся. Полные локальные memory protocol logs, ELF/raw/PPM/PNG сохраняются под `target/artifacts`; public report содержит text copies и hashes без пользовательских путей, ROM или производительских binaries.
