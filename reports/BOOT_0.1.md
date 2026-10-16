# Engineering Task 001 · Crosshair Boot 0.1

Дата результата: **16 октября 2026**, Asia/Yekaterinburg. Главное требование выполнено: собственное Rust-ядро действительно исполняется на ARM926 в QEMU, выдаёт требуемую строку и входит в проверенный контролируемый цикл ожидания. Это **VersatilePB**, не физический HTC Blue Angel.

Это сохранённый снимок Task001 из локального commit974a200. Код впоследствии расширен PXA reference; новые сборки могут иметь другие debug-info hashes. Текущие generated manifests создаются в target. Последующее E1 и его отдельные hashes: [отчёт](E1_PXA_REFERENCE.md).

```text
CROSSHAIR BOOT 0.1 — HELLO FROM RUST
PASS: real ARM926 execution, UART, SVC/stack, boot record and controlled idle
```

## Что реализовано и проверено

| Компонент | Проверка / результат |
|---|---|
| Rust Tier 3 | Локальный nightly-2025-03-01, rust-src, core source build, compiler_builtins, LLVM20.1.0; [версии](rustc.txt), [target-spec](target-spec.json), [cfg](target-cfg.txt) |
| Машинный образ | ELF32 little-endian ARM EABI5 soft-float; CPU_arch ARMv5TE, Thumb-1 разрешён, без dynamic loader/undefined symbols; PT_LOAD bytes совпадают с flat file |
| Собственное ядро | ARM entry → SVC/IRQ+FIQ mask → 8-byte aligned stack → BSS zero → Rust; no_std/no_main, initialized-data check, panic, ограниченная диагностика, terminal branch loop |
| BSP/драйвер | Отдельные VersatilePB BSP и PL011 polling TX; MMIO только эмулируемой платы, IRQ/DMA отключены |
| Normal boot | Точные UTF-8 UART bytes, PC=`0x10038` (`kernel_idle`), SP=`0x14320`, CPSR=`0x600001d3`, boot record magic=`0x43524f53`, stage=2, length=40 |
| Panic boot | `CROSSHAIR PANIC — HALTED`, тот же проверяемый terminal idle, stage=3; самостоятельный panic feature образ |
| BSS | Перед обоими стартами stage в BSS намеренно испорчен generic loader: `0xa5a5a5a5`; успешная загрузка требует очистки нашим entry |
| Связь результата с образом | Перед запуском пересчитываются SHA-256 текущих ELF/flat files; stale manifest отвергается до QEMU. Независимый негативный тест с подставленными hashes завершился ошибкой до создания PASS |
| Повторяемость | После удаления 62 release build files ядра и offline пересборки на том же хосте ELF/flat hashes совпали; [rebuild.json](rebuild.json). Core cache сохранён; межхостовая побайтовая идентичность не утверждается |
| ROM parser | 19 тестов, без skip: синтетический CAB через реальный libarchive, 1024 усечения NBA, bounds/names/counts, traversal/duplicates/truncation, XOR vector, CLI wrong-hash. Исправлены проверки и FFI cleanup; [журнал](test-suite.log) |

QEMU построен локально из официального tar **9.2.0**, с default ARM machines, TCG, без host audio/UI. Версии хоста: macOS x86_64, Apple clang21.0.0, Python3.12.13, GLib2.88.3, Pixman0.46.4, pkgconf3.0.8. Все файлы QEMU и Rust toolchain находятся в `local/`; глобальный default Rust не заменён. При первом запуске обнаружена необходимость явно связать VersatilePB audio backend: исправлено `-machine versatilepb,audiodev=audio0 -audiodev none,id=audio0`. [Полная конфигурация/версии](qemu/host-tools.txt), [source pins](qemu/source.txt).

## Артефакты

| BSP | ELF / flat bytes | Entry PA | Собственный RAM extent, включая 16 KiB stack | Статус |
|---|---|---|---|---|
| VersatilePB normal | 98 704 / 692 | `0x00010000` | 17 200 байт | Исполнен, PASS |
| VersatilePB panic | 96 908 / 532 | `0x00010000` | 17 040 байт | Исполнен, PASS |
| Blue Angel adapter | 63 496 / 500; padded HaRET 4096 | `0xa0008000` | 17 104 байта | Собран, статически проверен; аппаратно не исполнен |

ELF debug/header bytes не равны занятой гостевой RAM. Стек — статическая резервация, не измеренный worst-case расход. Манифесты и полные дизассемблирования: [normal](versatilepb/image.json), [panic](versatilepb-panic/image.json), [Blue Angel](blueangel/image.json). [Все hashes](artifacts-sha256.json).

Собственные исполняемые файлы находятся в `../target/artifacts/versatilepb/`, `versatilepb-panic/`, `blueangel/` и воспроизводятся скриптом. Бинарники исключены из Git; сохранённые здесь текстовые свидетельства относятся именно к hashes выше. [Normal UART log](versatilepb/qemu-uart.log), [normal CPU/RAM evidence](versatilepb/smoke-test.json), [ELF report](versatilepb/elf-report.txt), [машинный код](versatilepb/disassembly.txt), [panic evidence](versatilepb-panic/smoke-test.json).

Проверенные команды:

```sh
scripts/bootstrap-qemu.sh
scripts/test.sh
source scripts/env.sh
cargo fmt --all -- --check
shellcheck -x scripts/*.sh
cargo clean --release -p crosshair-boot --target armv5te-none-eabi
CARGO_NET_OFFLINE=true scripts/build.sh versatilepb
```

`scripts/test.sh` выполняет normal/panic QEMU tests, статическую проверку Blue Angel и parser tests, затем восстанавливает нормальный Cargo output. `verify_image.py` сохраняет header/attributes/disassembly/symbols/size. Отдельная независимая ревизия проверила ARM entry, linker, PL011, ELF→flat/padded bytes и hashes. Переноса реализации Linux/HaRET в ядро нет; первоисточники использованы для контрактов и аппаратных фактов, их GPL notices сохранены в локальных reference trees.

## Подготовлено, но не проверено на соответствующей платформе

Windows 11/WSL2 инструкция и зависимости — [BUILDING.md](../BUILDING.md). В этой сессии Windows не доступна, поэтому установка WSL и Linux-сборка не заявлены выполненными. Ручной GDB-сеанс подготовлен; автоматическая диагностика CPU/RAM проверена через QMP.

Blue Angel адаптер собран отдельно: собственный RAM log, общий ARM entry, отдельная PA карта. Исследованы два исходных snapshot HaRET и настоящий PXADroid EXE, включая 192 инструкции частичной binary/source map. Подтверждены raw-copy/+0x8000, tags/+0x100, r0-r2, отключение MMU/I/D; отсутствует доказательство всего binary/source соответствия и live состояния устройства. [Полный отчёт с подтверждёнными/неизвестными параметрами](../docs/BLUEANGEL_BOOT_RESEARCH.md).

## Что остаётся неизвестным

Свободные/резервные RAM-диапазоны конкретного PDA2k; полный boot-path выбранного HaRET; остаточное DMA/периферийное состояние; наблюдаемый физический канал диагностики и readback RAM log; GPIO/IRQ/калибровки и аппаратно проверенные драйверы; поведение возврата после RAM handoff. Нет exception vectors/abort handlers, IRQ scheduler, heap, LCD/ввода/GSM/питания в текущем ядре. Busy idle не является power-saving.

Полный повтор `inspect_blueangel.py` над ROM и пригодный PE `QwertyKey.dll` заблокированы отсутствующим исходным EXE (`ac59e0…e46c3`); старые manifests не объявлены новым анализом. M1 сохранён отдельным приоритетом: [точные offsets и будущие артефакты](../docs/RESEARCH_NEXT.md).

## crosshair-emulator

После успешного Boot начато отдельное проектирование: [feasibility](../crosshair-emulator/FEASIBILITY.md), [roadmap](../crosshair-emulator/ROADMAP.md). В **реально собранном QEMU9.2** доступны `versatilepb`/`arm926`, PXA CPU types сохранены, но Connex/Verdex/Mainstone boards отсутствуют: отдельные реальные probes завершаются `unsupported machine type`, exit1. Это [удаление upstream в9.2](https://github.com/qemu/qemu/blob/v9.2.0/docs/about/removed-features.rst#L1038), не случайно урезанная сборка. [Фактическая inventory](qemu/machine-availability.txt). Модели Blue Angel и GSM пока не реализованы, их точность не заявляется.

Конкретный следующий шаг ядра: закрыть полный boot-path/соответствие выбранного HaRET и подготовить доказанную диагностику перед физическим M2b. Параллельный M1 требует исходной ROM; `crosshair-emulator` развивается по своим проверяемым этапам. Устройство/Flash/Radio/CID/физическая SD в этой работе не затрагивались; ROM не публикуется; исходники доступны отдельным чистым экспортом.
