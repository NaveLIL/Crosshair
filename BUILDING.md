# Сборка Crosshair

## Wave007: User Shell и интерактивное окно macOS

```sh
scripts/run-crosshair-gui.sh
```

Команда собирает отдельный User ELF, встраивает его в ARM guest, компилирует небольшой AppKit frontend и открывает окно **Crosshair Shell0.1 — ARM QEMU**. Внутри работает `crosshair-blueangel-display-test` с настоящим ARM TCG: Shell, приложения, RGB565 rendering, системные вызовы и планировщик исполняются гостем. Окно получает свежие committed pixels через QMP `screendump`, показывает гостевые 240×320 в масштабе 2× по умолчанию и передаёт клавиши в существующий synthetic input FIFO. Это host adapter к проверенной модели; аппаратные ATI, клавиатура и сенсор PDA2k здесь не проверяются.

Щёлкнуть внутри окна для фокуса. Стрелки меняют выделение, Enter запускает выбранное действие, Escape возвращает назад. F10 открывает Menu, Home возвращает Desktop, F1/F2 — левая/правая softkey, F3 переключает открытый экран. На MacBook для F-клавиш может требоваться Fn; Home обычно доступен через Fn+← ([стандартные сочетания Apple](https://support.apple.com/en-ie/102650)). В Launcher обычные символы вводят настоящий ограниченный поисковый запрос, Backspace удаляет символ; проверен и кириллический ввод. Изменённая тема действует до reset. Закрытие окна или ⌘Q завершает frontend и его QEMU; окно остаётся открытым до этого действия. `scripts/run-shell.sh` — короткий alias той же команды.

Нужны прежние pinned Rust и QEMU display-test cache, а для окна — macOS AppKit и Swift compiler из Xcode Command Line Tools (`xcrun swiftc`). Новые Shell-команды через `scripts/shell-env.sh` находят стандартные `local/` caches и соседние caches публичного checkout; подготовленные `RUSTUP_HOME`/`QEMU_DISPLAY_TEST` сохраняют приоритет. Для чистой машины сначала выполнить существующие Rust/QEMU bootstrap-команды. Cocoa доступна в проверенном QEMU cache; выбранный frontend подключает keyboard events к synthetic FIFO и показывает фактический QEMU console framebuffer.

```sh
scripts/test-shell.sh       # host Shell tests, ARM session/parity, native pipeline на macOS
scripts/test-wave007.sh     # вся принятая цепочка Wave001–Wave006 и новый Shell
scripts/run-crosshair-gui.sh --headless-test  # реальный ARM/QEMU input/frame pipeline без окна
scripts/run-crosshair-gui.sh --window-test    # видимое окно и автоматические native keyDown events
```

На macOS `test-shell.sh` также кратко открывает настоящее окно и отправляет четыре `NSEvent keyDown` через AppKit: Launcher → About → Back → Home. Результат `gui/window-test-result.json` связывает этот маршрут с реальными ARM состояниями и QEMU frames. Автоматическое закрытие относится к `--window-test`; обычный запуск ожидает закрытия владельцем. Ручной ввод MacBook остаётся отдельной проверкой.

Образы находятся в `target/artifacts/shell/{user-image,image}/`, гостевые PNG 240×320, raw RGB565, QEMU PPM, actual state journals и host pixel references — в `target/artifacts/shell/execution/`. `gui/pipeline-result.json` содержит native keymap/PPM decoder checks, проверку нескольких событий в одном pipe write и ARM delivery; `gui/session-result.json` записывается при закрытии интерактивного окна. Тесты очередей используют отдельный автоматический session; interactive adapter применяет bounded backpressure перед hardware FIFO и kernel queue. UI state и нарисованные экраны в frontend не дублируются. Размер flat image включает адресные промежутки и отдельно учитывается от выделенной RAM.

### Иконки Shell

Основной каталог Shell использует выбранные Tabler Icons с сохранённой MIT лицензией и закреплённым upstream commit: `shell/assets/tabler/{LICENSE,PROVENANCE.json,selected/}`. Offline generator создаёт 54 монохромные 1bpp masks для 18 стабильных ID в размерах 12/16/24. В ARM image входят 2196 read-only байт masks; цвет задаёт текущая тема. SVG renderer и Python зависимости остаются инструментами подготовки на хосте.

```sh
python3 shell/tools/generate_icons.py --check
python3 shell/tools/test_generate_icons.py -v
# Полная сверка raster generation при установленном pinned host toolchain:
local/icon-tools/bin/python shell/tools/generate_icons.py --regenerate-check
```

Обычная сборка проверяет входные SVG, лицензию, provenance и generated Rust через Python stdlib. Для повторного raster generation нужны версии из `requirements.lock.json` и native Cairo1.18.4; Python packages закреплены с hashes в `requirements.txt`. `--generate` намеренно обновляет generated Rust и выходные hashes. `test-shell-ui.sh` дополнительно выполняет полную сверку, когда `local/icon-tools` уже подготовлен. Общий `crosshair-ui` и его исторические pixel fixtures сохранены.

## Wave005: отдельный User/MMU/SVC guest

Используются прежний Rust toolchain и **неизменённый E2B QEMU cache**; новая machine/overlay не нужна. `QEMU_E2B` выбирает существующий внешний cache как прежде. [Протокол](reports/WAVE_005.md), [security contract и ограничения](docs/SECURITY_MODEL.md), [модель угроз](docs/THREAT_MODEL.md).

```sh
scripts/bootstrap-qemu-e2b.sh  # Если E2B cache ещё не подготовлен.
scripts/test-security.sh      # Сборка, два host policy tests и24 TCG cases.
# Все принятые регрессии и новый эксперимент:
scripts/test-wave005.sh
```

`scripts/build-security.sh` создаёт `target/artifacts/security/image/`: отдельный `crosshair-security.elf`, flat BIN,64B vectors, attributes/disassembly/size/manifest и host policy test log. `tools/smoke_security.py` пишет24 case records и общий результат в `target/artifacts/security-tests/`; полный `scripts/test-wave005.sh` завершён exit0,24cases/48boots. Flat BIN содержит адресный gap и не равен working RAM; accounting приведён в отчёте. Harness запускает guest в QEMU; это не HaRET image. Фактически проверен macOS x86_64; новый WSL-прогон не заявляется. Криптографический compile-only probe имеет отдельный [manifest/reproducer](research/crypto-candidates.json) и не добавляет зависимостей ядру/UI.

## Wave004: UI внутри ARM guest

Используются прежние Rust nightly-2025-03-01 и отдельный QEMU9.2 overlay. Новый cache `local/qemu-display-test` требует pixman (на Linux: `libpixman-1-dev`; macOS: `pixman` через pkg-config); прежние E1/E2A/E2B caches не меняются. Native Cocoa backend компилируется на macOS, но фактически проверен headless `-display none` с настоящей QEMU graphical console и QMP screendump.

```sh
scripts/bootstrap-qemu-display-test.sh
# Короткий самостоятельный цикл: host references нужны до guest parity test.
scripts/test-ui.sh
scripts/test-display.sh
# Или единый запуск всех принятых регрессий и интеграции:
scripts/test-wave004.sh
```

`QEMU_DISPLAY_TEST=/absolute/path/to/qemu-display-test/bin/qemu-system-arm` выбирает внешний cache. Остальные `QEMU_SYSTEM_ARM`, `QEMU_PXA`, `QEMU_BLUEANGEL`, `QEMU_E2B` и `RUSTUP_HOME` сохраняют значения из предыдущих этапов. На этой волне все исполнения проведены на macOS x86_64; WSL2/Linux путь предусмотрен скриптами, нового WSL-прогона нет.

`scripts/build-display-test.sh` создаёт `target/artifacts/display-test/image/`: ARM ELF, flat RAM image,64B vectors, machine-code/size/attributes reports. `tools/smoke_display.py` запускает TCG, replay через отдельный synthetic FIFO, сохраняет guest `.raw565/.png`, actual QEMU `.ppm` и JSON результатов в `target/artifacts/display-test/execution/`. Эталонный экран после37 событий: `canonical-37.png`, `canonical-37.raw565`, `canonical-37.ppm`. Capture содержит настоящие гостевые пиксели; это не host mockup и не фотография PDA.

```sh
mkdir -p target/artifacts/wave004
scripts/test-wave004.sh >target/artifacts/wave004/all-tests.log 2>&1
python3 tools/collect_wave004_evidence.py
# Внешний cache: добавить --qemu-cache /absolute/path/to/qemu-display-test
```

Collector работает после exit0; `test-display.sh` автоматически выполняет негативную missing-reference check перед положительным replay. Новые text evidence сохраняются в `reports/wave004/`; прежние отчёты не перезаписываются. Собственные ELF/PNG/raw и полные QTest memory protocols остаются локальными; их hashes записаны в evidence. Команды не обращаются к PDA2k, ROM или физическим накопителям.

## Wave003: E2B и UI0.2

Сохраняются закреплённые nightly-2025-03-01 и QEMU9.1/9.2. Новый overlay собирается в отдельном `local/qemu-e2b`, не изменяя runtime E1/E2A:

```sh
scripts/bootstrap-qemu-e2b.sh
scripts/build-e2b.sh
scripts/build-e2b.sh --negative-test
scripts/test-e2b.sh
scripts/test-ui.sh
# Все принятые регрессии + E2B:
scripts/test-wave003.sh
```

Для внешних caches можно задать `QEMU_SYSTEM_ARM`, `QEMU_PXA`, `QEMU_BLUEANGEL`, `QEMU_E2B` абсолютными путями к соответствующим четырём runtime; `RUSTUP_HOME` — к уже подготовленной изолированной Rust installation. На чистом checkout bootstrap-скрипты используют свои проектные каталоги. На этой волне фактически проверен macOS x86_64; WSL2 остаётся основной предлагаемой Windows-средой, без заявления о новом WSL-прогоне.

Сборки E2B находятся в `target/artifacts/e2b/{normal,negative-test}`: ELF, flat RAM image, отдельные64B vectors, `image.json`, ELF attributes/disassembly/size. Запускает ELF только тестовый QEMU harness; это не образ для HaRET. Execution и QTest logs — `target/artifacts/e2b-tests` и `e2b-qtest`. UI PNG240×320, raw565 и37-event input trace — `target/artifacts/ui/ui02apps.png`, `ui02apps.raw565`, `ui02-input-trace.json`. [Протокол с памятью и границами](reports/WAVE_003.md).

Текстовые presentation copies после успешного полного прогона:

```sh
mkdir -p target/artifacts/wave003
scripts/test-wave003.sh >target/artifacts/wave003/all-tests.log 2>&1
python3 tools/collect_wave003_evidence.py
# При внешнем cache добавить: --qemu-cache /absolute/path/to/qemu-e2b
```

Collector проверяет статусы, hashes источников UI/образов/эмулятора и сохраняет прежние evidence. Он не запускает тесты и не заменяет завершённый exit0 полного скрипта.

Дополнение E1: собственный PXA reference guest и QTest на Connex/Verdex/Mainstone — [результаты](reports/E1_PXA_REFERENCE.md). Отдельные команды: `scripts/bootstrap-qemu-pxa.sh`, затем `scripts/test-pxa-reference.sh`. QEMU9.1 устанавливается в `local/qemu-pxa` независимо от QEMU9.2. Это тестовая база, не команда для Blue Angel.

Состояние на 16.10.2026: ARM ELF собран на macOS x86_64. Основная рекомендуемая среда для Windows 11 — WSL2/Ubuntu 24.04. В этой сессии доступа к Windows/WSL нет: команды ниже подготовлены, но их исполнение на Windows не подтверждено. XP/VMware остаётся средой обслуживания WM, не инструментальной средой ядра.

## Закреплённые инструменты

| Инструмент | Версия / назначение |
|---|---|
| Rust | `nightly-2025-03-01`, rustc `1.87.0-nightly`, commit `287487624357c19b22d27aa3ed584b8ccd080b4d` |
| Cargo / LLVM | Из того же toolchain; LLVM `20.1.0`, `rust-lld`, `llvm-objcopy`, `llvm-readobj`, `llvm-objdump`, `llvm-nm`, `llvm-size` |
| Rust components | `rust-src`, `llvm-tools-preview`, `rustfmt`; профиль minimal |
| Цель | Встроенная `armv5te-none-eabi`; `core` и compiler builtins собираются из исходников через Cargo `build-std` |
| QEMU | `9.2.0` из официального tar; SHA-256 `f859f0bc65e1f533d040bbe8c92bcfecee5af2c921a6687c652fb44d089bd894` |
| QEMU build helpers | Meson `1.5.0`, Ninja `1.11.1.3`, distlib `0.3.9`, pycotap `1.3.1` в local venv |
| Python | 3.10+ для инструментов проекта; на хосте проверен 3.12.13 |

Это рабочая проверенная комбинация Rust, а не утверждение о самой ранней поддерживающей версии. Отсутствие prebuilt `rust-std` для Tier 3 ожидаемо; `rustup target add` не используется. У ядра нет внешних runtime Cargo dependencies; display-test использует собственный UI path dependency. Source tree стандартной библиотеки закреплён датой toolchain и содержит свой Cargo.lock (`compiler_builtins 0.1.148`).

Источники: [официальная цель Rust](https://doc.rust-lang.org/rustc/platform-support/armv5te-none-eabi.html), [Cargo build-std](https://doc.rust-lang.org/nightly/cargo/reference/unstable.html#build-std), [rustup installation](https://rust-lang.github.io/rustup/installation/index.html). Фактическая конфигурация выбранного компилятора сохранена в `reports/target-spec.json`, `target-cfg.txt`, `rustc.txt`, `cargo.txt`.

## Windows 11 / WSL2

В PowerShell администратора на Windows 11:

```powershell
wsl --install -d Ubuntu-24.04
wsl --list --verbose
```

После требуемой Windows перезагрузки создать пользователя Ubuntu. У дистрибутива должна быть версия WSL 2; при необходимости `wsl --set-version Ubuntu-24.04 2`. Источник: [Microsoft WSL installation](https://learn.microsoft.com/en-us/windows/wsl/install). Не выполнять эти Windows-команды в XP VM.

В Ubuntu хранить checkout в Linux home, например `~/src/crosshair`, затем из корня проекта:

```sh
sudo apt-get update
sudo apt-get install -y build-essential python3 python3-venv curl ca-certificates \
  git pkg-config libglib2.0-dev libpixman-1-dev libarchive13 gdb-multiarch xz-utils
# Если rustup ещё нет: установить его по официальной инструкции rustup выше.
scripts/bootstrap-rust.sh
scripts/bootstrap-qemu.sh
scripts/test.sh
```

QEMU собирается локально, поэтому версия дистрибутивного `qemu-system-arm` не влияет на основной путь. Пакеты хоста не закреплены побайтно; их версии надо сохранять на новом ПК. Скрипт пишет `local/qemu/evidence/host-tools.txt`. Для проверки только с уже установленным QEMU можно задать `QEMU_SYSTEM_ARM=/absolute/path/qemu-system-arm`; такая замена требует повторного smoke test и фиксации версии.

На macOS нужны Xcode command line tools, Python с venv, GLib/Pixman development files и `pkg-config`. Проверенная локальная сборка и диагностика bootstrap описаны в `reports/BOOT_0.1.md`. Скрипт Rust использует **проектный** `local/toolchains/rustup`, не заменяет глобальный default toolchain. В новом shell можно выполнить `source scripts/env.sh` перед ручными Cargo-командами.

## Сборка, исполнение, проверка

```sh
scripts/build.sh versatilepb
scripts/run-qemu.sh
# Завершение ручного сеанса: Ctrl+C.
```

```sh
# Ограниченный по времени автозапуск, UART + QMP-проверка состояния CPU/RAM:
python3 tools/smoke_qemu.py
# Все проверки: normal boot, panic boot, compile-only Blue Angel, parser tests:
scripts/test.sh
```

Выходы — `target/artifacts/versatilepb/`: `crosshair-boot.elf`, сырой `crosshair-boot.bin`, `image.json` с SHA-256/символами/сегментами, `elf-report.txt`, `disassembly.txt`, `size.txt`; после теста `qemu-uart.log`, `qemu-stderr.log`, `smoke-test.json`. `versatilepb-panic/` содержит самостоятельную тестовую panic-сборку. Завершающая нормальная сборка восстанавливает основной Cargo output после выбора BSP.

```sh
# Только сборка и статическая проверка, НЕ команда для устройства:
scripts/build.sh blueangel
```

`target/artifacts/blueangel/` содержит ELF с entry `0xa0008000`, flat `.bin` и дополненный нулями до 4 KiB `crosshair-haret.bin`. BSS/stack не включены в flat file, но ограничены линкером. Эти образы на КПК не исполнялись. HaRET/source match и аппаратные предусловия остаются открыты: [исследование](docs/BLUEANGEL_BOOT_RESEARCH.md).

## ABI и ограничения ARMv5TE

Компилятор выдаёт ARM A32 по умолчанию, допускает Thumb-1 interworking, не Thumb-2. Little endian, 32-bit pointers, AAPCS/EABI5, 8-byte stack alignment, soft-float, strict alignment. Нет зависимости от Linux ABI, libc, CE, hosted startup, heap или `alloc`. Для ARMv5 нет `cpsid`, `ldrex/strex`, `dmb`, `movw/movt`, аппаратного integer divide; entry использует `msr cpsr_c`.

В **фактическом** `rustc --print cfg`: `target_has_atomic_load_store` для 8/16/32/ptr, но **нет `target_has_atomic`**; в target-spec `atomic-cas=false`. Это не обещание `AtomicU32::compare_exchange`/lock-free RMW и не совместимость с libatomic. В коде Boot атомики не используются. Volatile MMIO обеспечивает наблюдаемые обращения, но не заменяет аппаратные барьеры или синхронизацию; корректность текущего UART основана на MMU/cache-off, одном CPU, masked IRQ/FIQ и отсутствии DMA.

`verify_image.py` требует ELF32 ARM executable, EABI5 без hard-float, ARMv5TE attributes, отсутствие PT_INTERP/PT_DYNAMIC/undefined symbols, корректный entry и стек. Полное дизассемблирование сохраняется для ревизии; атрибуты сами по себе не доказывают исполнение всех возможных путей. QEMU ARM926 тест реально исполняет normal и panic пути. UART timeout и аппаратные исключения пока отдельно не инжектировались.

## Отладка

```sh
scripts/run-qemu.sh -S -gdb tcp:127.0.0.1:1234
# В другом Linux/WSL terminal:
gdb-multiarch target/artifacts/versatilepb/crosshair-boot.elf
```

В GDB: `target remote 127.0.0.1:1234`, `break rust_main`, `continue`, `info registers`, `p CROSSHAIR_BOOT_RECORD`, `disassemble _start`. Номер порта привязан к loopback. Опция QEMU `-d guest_errors,unimp -D target/qemu-debug.log` сохраняет ошибки модели. Автотест использует QMP через временный Unix socket, останавливает CPU и проверяет PC/CPSR/SP/boot record без semihosting. Ручной GDB-сеанс пока не входит в подтверждённые результаты.

`target/` и `local/` исключены из Git. После bootstrap и первого скачивания crates core можно пересобрать с `CARGO_NET_OFFLINE=true scripts/build.sh versatilepb`. Побайтовая идентичность ELF между разными хостами не утверждается: debug info содержит пути. Проверенная повторяемость одного хоста фиксируется в отчёте.

## E2A и следующая волна

```sh
scripts/bootstrap-qemu-blueangel.sh
scripts/test-e2a.sh
# После установки обеих эталонных сборок и E2A — вся регрессия + UI:
scripts/test-next-wave.sh
```

E2A использует собственный минимальный QEMU9.2 overlay в `local/qemu-blueangel`; QEMU9.1 reference и vanilla9.2 не меняются. Для внешних установок задать `QEMU_SYSTEM_ARM`, `QEMU_PXA`, `QEMU_BLUEANGEL` отдельными абсолютными путями. `CROSSHAIR_QEMU_BLUEANGEL_DIR` задаёт отдельный build/cache; прочие cache options описаны в [host model README](crosshair-emulator/qemu/README.md). Новый bootstrap реально выполнен на macOS; Linux/WSL пока подготовлен, но не проверен. На macOS копии необходимых host helpers и собственного QEMU очищаются от extended attributes и подписываются ad-hoc; глобальные настройки безопасности и baseline executables не меняются. [E2A report](reports/E2A_MINIMAL_BOARD.md).

UI проверяется отдельно командой `scripts/test-ui.sh`: host tests запускаются из нейтрального временного каталога, чтобы kernel Cargo config с `build-std` не влиял на host target. Затем тот же библиотечный source компилируется под ARMv5TE. PNG/raw565 и текстовые проверки сохраняются в `target/artifacts/ui/`; [ограничения и память](docs/UI_0.1.md).
