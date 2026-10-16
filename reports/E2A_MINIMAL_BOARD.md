# E2A — Minimal Virtual Blue Angel

**Реализовано и проверено, 16.10.2026:** собственная экспериментальная QEMU machine `crosshair-blueangel-e2a` действительно исполняет Rust Crosshair, обрабатывает timer IRQ и повторно загружается после `system_reset`. E2A завершён в пределах RAM/loader/test UART/4 timers/PIC subset. Это **PXA260 ISA proxy**, не аппаратно точный PXA263 и не готовый эмулятор телефона.

Входной принятый baseline: `79ffcbd9c7beec6ac0165da1fe57511eb83a4538`, уже включённый в public main merge `4d7c75e`. Boot0.1/E1 не переосмыслялись и не заменялись. Новая реализация отделена от эталона QEMU9.1 и от MIT ядра: [host C/лицензия](../crosshair-emulator/qemu/README.md), [CPU evidence](../docs/E2A_CPU_PROFILE.md), [полный контракт](../docs/E2A_CONTRACT.md).

## Фактический результат

```text
CROSSHAIR E2A — UART TIMER IRQ PASS
CROSSHAIR E2A — UART TIMER IRQ PASS
```

Это два UART сообщения гостя в одном QEMU process: первая загрузка и повтор после настоящего QMP `system_reset`. Каждая прошла BSS poison/readback перед выполнением ARM entry, CP15 MIDR=`0x69052903`, три входа в ARM IRQ vector с exception return, отдельный4KiB IRQ stack,16KiB SVC stack, W1C ack, masks и terminal idle с CPSR low byte=`0xd3`. PC проверен по ELF symbol `kernel_idle`, а не по наличию строки. UART здесь тестовый; на настоящем Blue Angel FFUART исторически связан с GSM.

Отдельный negative-test ELF реально исполнил четыре изолированных probe:

| Probe | Наблюдение TCG |
|---|---|
| Read PA `0x40a00020` | Unsupported timer offset → data abort |
| Write PA `0x40d00000` | RO ICIP → data abort |
| Byte read PA `0x40a00010` | Timer width violation → data abort |
| Read PA `0x50000000` | Unmapped address → data abort |

Каждый требует stage5, DFSR low code8 и модельный EA bit12 (1 для MEMTX_ERROR,0 для unmapped DECODE_ERROR), точный DFAR, zero IRQ count, UART `CROSSHAIR E2A — DATA ABORT PASS` и terminal SVC idle. Первый вариант selector в ELF `.data` был отвергнут тестом: QEMU ROM reset возвращал compiled selector1. Исправленный тестовый mailbox PA `0xa0000100` вынесен за ELF/BSS; теперь проверены **все четыре разных** адресных сценария.

E2A harness также измеряет BSS до entry: запускает TCG с `-S`, после reset пишет A5 через QTest physical-memory server, проверяет readback и только затем делает QMP `cont`. Поле `pre_entry_stage=2779096485` сохранено для обеих загрузок и каждого abort probe. Это усиливает доказательство очистки BSS без зависимости от порядка loader callbacks; прежние E1/Boot scripts сохранены.

Независимый QTest (dummy CPU, без guest instructions) прошёл:

- UART byte `0x51`; ровно3 686 400 OSCR ticks за1 000 000 000 virtual ns.
- OIER match gating; disabled match не создаёт OSSR, late enable не восстанавливает его.
- Raw pending против ICMR, IRQ/FIQ routing и **реальные выходные переходы** `/machine/e2a`: raiseIRQ, lowerIRQ, raiseFIQ, lowerFIQ, raiseFIQ, lowerFIQ.
- Latched OSSR сохраняет источник при OIERdisable до W1C; независимое acknowledgement channels0/1.
- OSCR modulo2³² и match через rollover.
- Reset всех OSMR/OSCR/OIER/OSSR и PIC mask/route/pending, deassertIRQ/FIQ; отмена старых callbacks проверена с **повторно включёнными OIER/ICMR**, чтобы маски не скрывали ошибку. Новый timer IRQ после reset работает.
- Invalid MMIO не меняет реализованные регистры и даёт диагностическую запись. QTest не выдаёт MemTxResult, поэтому доказательство data abort дают отдельные TCG probes выше.

[Text evidence manifest](../crosshair-emulator/evidence/e2a/manifest.json), [boot/reset](../crosshair-emulator/evidence/e2a/execution/boot-reset/result.json), [QTest result](../crosshair-emulator/evidence/e2a/qtest/result.json), [protocol](../crosshair-emulator/evidence/e2a/qtest/protocol.log). Это presentation copies с нормализованными host/socket paths; исходные guest hashes не изменены. Не аппаратные traces.

## Сборка и машинный код

QEMU9.2.0 upstream commit `ae35f033b874c627d81d51070187fbf55f0bf1a7`, официальный archive SHA256 `f859f0bc65e1f533d040bbe8c92bcfecee5af2c921a6687c652fb44d089bd894`. Host overlay SHA256 `49e5b31e36f22240e2fd95035566085f0d8430d1abf6b30ef635d152e517ec32`. Проверенный native macOS x86_64 QEMU binary SHA256 `ea9dbd311573eda256ec3c4057305af0f8b73f8002e3ab922115c960acda1458`; другой host не обязан давать тот же executable hash.

Rust toolchain сохранён nightly2025-03-01. Оба ELF проверены как freestanding ELF32 little-endian ARMv5TE EABI5 soft-float, без dynamic loader/undefined symbols. Entry PA `0xa0008000`; normal RAM extent21 672bytes, из них20KiB зарезервированы для двух стеков; отдельные64bytes vectors. Heap/allocator/Linux runtime отсутствуют. Worst-case stack usage пока не измерен. [Normal image manifest](../crosshair-emulator/evidence/e2a/images/normal/image.json), [ELF](../crosshair-emulator/evidence/e2a/images/normal/elf-report.txt), [disassembly](../crosshair-emulator/evidence/e2a/images/normal/disassembly.txt).

```sh
scripts/bootstrap-rust.sh
scripts/bootstrap-qemu-blueangel.sh
scripts/test-e2a.sh
# Текстовые presentation copies после успешных тестов:
python3 tools/collect_e2a_evidence.py
```

На текущем хосте bootstrap полностью выполнен. macOS потребовал очистки extended attributes и ad-hoc подписи **собственных копий** host helpers/QEMU: unsigned executables зависали ещё до main. Скрипт закрепляет helpers и изолирует Darwin build PATH; глобальные toolchains и настройки безопасности не менялись. Windows/WSL сборка этого нового overlay ещё не исполнялась.

Локальные выходы `target/artifacts/e2a/{normal,mmio-test}/crosshair-e2a.elf`, `.bin`, `vectors.bin`, `image.json`, ELF report/disassembly доступны после сборки. Никаких OEM образов нет. Тесты и сборка не обращались к физическому PDA/SD.

## Сравнение с E1

| Свойство | E1 QEMU9.1 reference | E2A QEMU9.2 own board |
|---|---|---|
| Boards | Connex/Verdex/Mainstone upstream | Собственная композиция `crosshair-blueangel-e2a` |
| CPU | PXA255 / PXA270-C0 / PXA270-C5 | PXA260 proxy, модельный MIDR69052903 |
| RAM |64 /256 /64MiB |128MiB synthetic contiguous |
| Timer |25x3.6864MHz /27x3.25MHz |4 channels3.6864MHz |
| OIER/OSSR | Gated match, latched status | Сохранена проверенная subset семантика; interpretation Intel описана отдельно |
| Timer reset | Состояние сохраняется, известное ограничение | Состояние сбрасывается, старые deadlines отменяются |
| MMIO | Поведение исторических устройств | Строгий subset с transaction errors/data abort |
| Loading | Gumstix synthetic pflash+loader / Mainstone ELF | Synthetic64B vector RAM + generic ELF loader; Flash не требуется |
| Проверки |3×TCG guest +3×QTest | Две загрузки,4×abort guest + QTest outputs/reset |

`scripts/test.sh` и `scripts/test-pxa-reference.sh` повторно прошли: normal/panic Boot, compile-only HaRET image,19 parser tests, все3 reference guest и3 QTest. E1 RAM binary SHA256 остался `6fe8287d4c3f4376dd58fefee7241ebdfe41e37b82a69faddb588fda40481920`; vectors `c743923832589ead31c43d6d30536907d49df0607b4e735b9a1e35d3ff35f2c5`. ELF debug data меняются при изменении строк условного исходника; executable bytes сохраняются. Старые результаты E1 и его скрипты не перезаписаны.

## Неподтверждённые допущения и следующий рубеж

**Источник, без hardware validation:** ARMv5TE/26x distinctions,90GPIO против85 у255, timer/PIC addresses,4 matches и частота. PXA263 имеет integratedFlash, выбор CPU260 её не реализует. **Интерпретация:** latched-status routing после OIERdisable. **Экспериментальные решения:** contiguous128MiB RAM,64B low vectors, ELF loader, test UART, edge rounding/full-wrap equality и нулевой reset нашего subset. **Неизвестно:** настоящий MIDR/stepping/errata, CP14/15 полнота, RAM banks/aliases/reservations, clocks/power/reset types, cache/DMA behavior и диагностика конкретного HTC.

GPIO/ASIC3, ATI Imageon W3200 LCD, TSC2200, GSM/SDIO/Wi-Fi/audio не реализованы. Для дисплея следующий результат — source-traced ATI aperture/register/stride/panel-mode contract, затем отдельная display model и target adapter. PXA LCD не подменяет ATI. UI0.1 следует отдельным software renderer без зависимости от этого оборудования; его тесты и память описаны отдельно. Приоритет M1 QwertyKey.dll сохранён и этим этапом не закрыт.
