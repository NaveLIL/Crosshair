# Технические источники

Первичный код и документация задают проверяемые контракты, но не заменяют испытания конкретной платы. Имена DLL и TOC offsets не являются готовыми драйверами.

<a id="s03"></a>
## S03 · Rust ARMv5TE

[Официальная цель armv5te-none-eabi](https://doc.rust-lang.org/rustc/platform-support/armv5te-none-eabi.html). Фактическая выбранная версия и ограничения — [BUILDING.md](BUILDING.md).

<a id="s04"></a>
## S04 · Cargo build-std

[Сборка core из исходников](https://doc.rust-lang.org/cargo/reference/unstable.html#build-std).

<a id="s06"></a>
## S06 · HaRET / PXADroid

[PXADroid](https://sourceforge.net/p/pxadroid/wiki/Home/), [HaRET source](https://github.com/KevinOConnor/haret). Закреплённые commits, boot contract и предел binary/source соответствия: [исследование](docs/BLUEANGEL_BOOT_RESEARCH.md).

<a id="s08"></a>
## S08 · FFI

[Rustonomicon FFI](https://doc.rust-lang.org/nomicon/ffi.html). Все unsafe/FFI участки проекта должны иметь локальный контракт.

<a id="s09"></a>
## S09 · Cargo profiles

[Профили сборки](https://doc.rust-lang.org/cargo/reference/profiles.html).

## QEMU и Blue Angel

[QEMU9.2.0](https://github.com/qemu/qemu/tree/v9.2.0), [PXADroid kernel commit 3712fd6](https://sourceforge.net/p/pxadroid/pxakernel/ci/3712fd6f197113f19959eba85b3628b202e30d64/tree/). Пути, commits и SHA-256 исторических моделей: [source manifest](crosshair-emulator/evidence/qemu-source-manifest.json).

## Статическая ROM-инвентаризация

[Исторический отчёт](research/initial_static_report.md), [package manifest](research/package_report.json), [TOC inventory](research/rom_inventory.json). Это каталог известного ROM-пакета, не аппаратный дамп и не новый полный rerun. ROM bytes не включены.

E2A: узкое сравнение CPU с Intel PXA26x Developer’s Manual278638-002, EMTS278640-002 и закреплённым PXADroid/QEMU кодом, точные URL/хеши/границы выводов — [CPU profile](docs/E2A_CPU_PROFILE.md). Происхождение GPL host subset — [QEMU overlay README](crosshair-emulator/qemu/README.md).

UI bitmap font: MIT Cozette v.1.30.0, pinned source/release hash, полный copyright notice и детерминированный subset — [provenance](ui/third_party/cozette/PROVENANCE.json), [font license](ui/third_party/cozette/LICENSE).

Wave003: [E2B CP14/CP15/reset/GPIO audit](docs/E2B_CPU_GPIO_AUDIT.md) содержит точные разделы Intel278638-002, encodings, закреплённые QEMU/PXADroid commits и повторно сверенные SHA-256 четырёх CPU/MMU source files. Source contract, интерпретация GPIO gating и synthetic choices отделены от [реальных QTest/TCG результатов](reports/WAVE_003.md).

Wave004: [ATI W3200 specification](docs/ATI_W3200_SPEC.md) и [девять pinned source hashes](research/w3200-sources.json) отделяют historical Linux/HaRET facts от unknown hardware properties. Собственный synthetic display/input backend не использует эти адреса и не выдаётся за W3200; [исполненные проверки](reports/WAVE_004.md) относятся к отдельному test-only contract.

Wave005: [SECURITY_MODEL](docs/SECURITY_MODEL.md) связывает ARM DDI0100I legacy AP/domain semantics и отсутствие современного XN с собственным User/MMU/SVC кодом; [THREAT_MODEL](docs/THREAT_MODEL.md) отделяет действующие границы от будущих filesystem/modem/network/loader services. [Результаты](reports/WAVE_005.md) относятся к неизменённому synthetic E2B, не PXA263 hardware. [Crypto candidate manifest](research/crypto-candidates.json) закрепляет официальные crate sources/checksums/VCS revisions, exact probe/lock и compile-only evidence. Исторические NCC/Quarkslab audits не выдаются за аудит всех текущих версий или интеграции; entropy/keystore/secure boot остаются неподтверждёнными.
