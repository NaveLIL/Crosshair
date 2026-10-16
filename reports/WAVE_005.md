# Wave005: Security Foundation 0.1

16.10.2026. Принятая база — `main a509d2ebed92f200627bb3a97522a2622db0420a`. **Реализовано и проверено:** собственный ARMv5TE код выполняется в User Mode, вызывает разрешённый SVC и получает результат; MMU запрещает ему kernel/MMIO access. После ошибочного пользовательского контекста ядро сохраняет состояние и запускает свежий healthy User контекст, который снова выполняет настоящий syscall. Физический PDA2k не использовался; Flash, Radio, ROM и физическая SD не затрагивались.

Полный `scripts/test-wave005.sh` завершился **exit0**: все прежние регрессии и **24 сценария / 48 boot-reset executions** нового эксперимента. [Общий журнал](wave005/all-tests.log), [сводка security tests](wave005/security/result.json), [проверка происхождения и hashes](wave005/validation.json). Это отдельный небольшой исполняемый прототип, не готовый application supervisor или сертификат безопасности.

## Что исполняется

Добавлен отдельный `crosshair-security` с feature `security-test`: [Rust kernel](../src/security.rs), [ARM entry и trap return](../src/arch/security_entry.S), [чистая copy-in policy](../src/security_policy.rs), [linker](../link/security.ld). Прежние гости и модели QEMU сохранены. Используется **неизменённая `crosshair-blueangel-e2b`**, QEMU9.2, CPU260 proxy. Она не стала точной PXA263; UI Wave004 по-прежнему исполняется в своём privileged guest.

ELF загружается по физическим адресам до включения MMU. Entry очищает BSS, устанавливает отдельные SVC/IRQ/ABT/UND stacks и low vectors. MMU остаётся включённой: `SCTLR=0x79`, caches off, `PID=0`, `DACR=1` — domain0 **Client**, поэтому AP permissions действительно применяются. Kernel RAM, privileged aliases пользовательских физических страниц, vectors и MMIO имеют AP1: privileged RW, User no access. Все остальные L1/L2 descriptors по умолчанию отсутствуют.

| User VA, half-open | Backing PA | Доступ User |
|---|---|---|
| `[01000000,01001000)` | `a0200000` | RO code, AP2 во всех четырёх1KiB subpages |
| `[01001000,01002000)` | `a0201000` | RW data, AP3 |
| `[01002000,01003000)` | Нет mapping | Guard, translation fault |
| `[01003000,01004000)` | `a0203000` | RW stack, AP3; initial SP=`01004000` |

16KiB L1 и1KiB coarse L2 находятся в privileged RAM с проверенным linker alignment. User получает контролируемые PC/SP и `SPSR=0xd0`: ARM User, IRQ/FIQ masked. Exception entry сохраняет64B frame на banked privileged stack. SVC return восстанавливает registers/LR/SPSR; завершение контекста возвращается через сохранённый kernel-owned SVC frame. User не выбирает kernel stack, exception target, TTBR/DACR или privileged CPSR.

### Небольшой syscall ABI

Разрешён ARM `svc #0` из установленного RO fixture code, номер в r7. `0=Exit` завершает текущий контекст, `1=Copy` принимает r0=User pointer, r1=length, копирует максимум64B в фиксированный kernel buffer и возвращает длину в r0. Это диагностический copy-in, без файловых, телефонных или MMIO полномочий. Проверяются cap, `checked_add` и **весь** разрешённый диапазон data page до первого чтения. Ошибки: `-ENOSYS=-38`, `-EFAULT=-14`, `-EINVAL=-22`; cap имеет приоритет. Нулевая длина допустима только с указателем в закрытом диапазоне data start..end, null/zero отвергается. Read-only code pointer также отвергается политикой этого ABI.

Неподдержанный SVC origin, включая User RW data и Thumb, завершает пользовательский контекст. Kernel проверяет принадлежность/alignment/размер инструкции перед чтением opcode; unmapped PC не читается и не вызывает kernel assert. Data/prefetch abort и UNDEF также завершают текущий User контекст. Затем проверяются kernel canaries, очищаются User data/stack и copy buffer, запускается фиксированный healthy context. Его настоящий User SVC копирует15B `CROSSHAIR USER\n`, возвращает15, User сохраняет полученный результат/CPSR и выполняет Exit. Только после внешних проверок весь сценарий считается PASS.

Это два последовательных контекста и trusted recovery fixture. General process loader, scheduler, устойчивые app identities, capability manager и универсальное восстановление произвольных приложений не реализованы. Nontrapping User loop при masked IRQ может удержать CPU; timeout host harness не является guest preemption.

## Реальные отрицательные и контрольные тесты

[Harness](../tools/smoke_security.py) проверяет actual CPU registers, RAM и instructions независимо от diagnostic banner. Каждый case исполняется дважды в одном QEMU process через `system_reset` с новым entry/BSS initialization. Прежние snapshots не засчитываются; partial `--case` помечается `complete_suite=false` и не пригоден для полного отчёта.

| Cases | Фактический результат |
|---|---|
| 00,18 | Разрешённые copy15 и copy64; actual bytes/digest/return в User Mode |
| 01–04 | LDR/STR kernel RAM и UART MMIO дают Data Abort, DFSR status`0xd` (section permission); запрещённая запись не выводит `X` в UART |
| 05,14 | Неизвестный r7 и неправильный SVC immediate возвращают `-38`; User реально продолжает исполнение |
| 06–10,17,19 | Null, kernel pointer, crossing end, len65, address wrap, code pointer и null/zero отвергнуты до копирования |
| 11 | Data end + zero length возвращает0 без чтения |
| 12,13 | Запись RO code: page permission`0xf`; unmapped guard read: page translation`0x7` |
| 15 | Привилегированный CP15 MRC из User даёт настоящий UNDEF; opcode`ee110f10` |
| 16 | Собственные benign инструкции из RW data **исполняются** и возвращаются к RO code: положительный контроль отсутствия XN |
| 20,22 | ARM SVC из RW data и Thumb SVC`df00` безопасно завершают контекст по narrow ABI; проверены SVC mode/LR/SPSR |
| 21,23 | Fetch с VA`02000000`: Prefetch Abort, IFSR status5, LR`02000004`; ARM UDF из RW data: UNDEF, opcode`e7f000f0` |
| Все24 | Kernel survives, свежий healthy User выполняет Copy/return/Exit; повтор после reset также PASS |

DFSR.WnR на используемом ARMv5 CPU отсутствует: чтение/запись различаются по фактическому LDR/STR opcode из загруженного ELF/RAM, а не по вымышленному биту. Проверены правильные LR corrections, User SPSR и текущий exception mode, все4096 L1 и256 L2 entries, privileged aliases, kernel/copy guards, remote RAM sentinel, физический guard sentinel, неизменность code page, banked stack/frame bounds и фактические recovery instructions. Сохранённые FNV digests — тестовые checksums, не криптографические MAC.

Чистая policy имеет **2 host tests**, включая100000 детерминированных pointer/length combinations с отдельным64-bit oracle: [журнал](wave005/image/policy-host-tests.log). Это дополняет48 ARM executions, а не заменяет их. UART byte-exact журнал каждого case содержит два `CROSSHAIR SECURITY — USER ISOLATION PASS` с CRLF; JSON фиксирует actual exception evidence. Например, [kernel read](wave005/security/case-01/result.json), [MMIO write](wave005/security/case-04/result.json), [prefetch fault](wave005/security/case-21/result.json), [Thumb SVC](wave005/security/case-22/result.json).

## RAM и машинный код

[ELF manifest](wave005/image/image.json), [attributes/segments](wave005/image/elf-report.txt), [disassembly](wave005/image/disassembly.txt), [size](wave005/image/size.txt). ELF32LE ARMv5TE, EABI5, soft float, без dynamic loader, imports, undefined symbols, `std`, allocator или Linux runtime. Криптографических dependencies в образе нет.

| Измерение | Bytes |
|---|---:|
| Kernel RAM extent `_start..__image_end`, включая alignment | **78848** |
| BSS внутри extent, включая page tables/records/guards |33792|
| SVC / IRQ / ABT / UND stacks внутри extent |16384 /4096 /4096 /4096|
| L1 / L2 внутри BSS |16384 /1024|
| User code:480B в отдельной зарезервированной page |4096|
| User data / User stack |4096 /4096|
| Kernel + три User pages |91136|
| Отдельные low vectors |64|
| **Итого зарезервировано экспериментом** | **91200** |
| Flat BIN на диске, включая gap до PA`a0200000` |2064864|
| Debug ELF на диске |1120060|

Неподключённый User guard не требует backing page; sentinel, записываемый host в её физический probe address, является тестовой оснасткой. Flat image gap не равен working RAM. Итог `llvm-size` text4035/data0/bss62464 также не равен RAM extent: он суммирует sections, включая NOLOAD stacks, без всех alignment gaps. Относительно отдельного E2B guest extent69632B kernel extent увеличился на9216B (8KiB ABT/UND stacks и1KiB L2); вместе с тремя User pages — на21504B, без64B vectors, общих для обеих платформ. Это сравнение diagnostics, не размер будущего process manager. Stack sizes — reservations с проверенными границами exception frames в этих сценариях; unmapped User guard проверен отдельно, не доказанная верхняя граница всех будущих путей.

Runtime QEMU SHA-256=`934861b3766fe0de5a7cf0ac766a12284887c01753ee0091f363d5b36ee274d2`; flat image SHA-256=`9d821b0204f8fce18dd0d5bf41dc91777f42f933c6b747e319ad7d7ead7b8e30`. Манифесты связывают конкретные source/image/runtime bytes с результатом; hashes не аутентифицируют загрузчик.

## Модель безопасности и будущая криптография

[SECURITY_MODEL.md](../docs/SECURITY_MODEL.md) задаёт TCB, process/driver/filesystem/modem/network/loader boundaries, ARMv5 AP/domain ограничения и будущие service contracts. [THREAT_MODEL.md](../docs/THREAT_MODEL.md) фиксирует assets, capabilities, objectives, assumptions, attack surfaces и severity calibration. Будущие угрозы обозначены как условные гипотезы, а не найденные remote vulnerabilities отсутствующих сервисов. Независимая статическая ревизия trap/return и harness помогла устранить kernel assert на неподдержанном User PC; cases20–23 воспроизводимо проверяют исправленные пути. Это не полный security scan.

CSPRNG, owner-bound SecretStorage, strict signature verification и AEAD описаны как **контракты, без runtime реализации**. Нет проверенного источника энтропии, генерации долгосрочных ключей, key storage, подписанного loader или SD encryption. CSPRNG должен сообщать `Unavailable`, пока источник/seed/reseed policy не доказаны. AEAD требует уникальных nonce, authenticated metadata и отказа без выпуска plaintext; подпись требует доверенного public key и exact payload binding. Подпись сама по себе не создаёт hardware secure boot/anti-rollback.

[Закреплённый manifest](../research/crypto-candidates.json) и [compile evidence](wave005/crypto/compile-compatible.log) содержат отдельный воспроизводимый ARM compile-only probe: `chacha20poly1305=0.11.0` и `ed25519-dalek=3.0.0`, defaults off, zeroize on, без runtime alloc/std/getrandom. Скомпилированы detached AEAD open и Ed25519 `verify_strict`; **функции не исполнялись**, keygen/signing не вызывались. Получен relocatable ARM object43892B, не runnable subsystem и не оценка RAM/latency.

Fresh dependency resolution выбрала `sha2=0.11.1` с MSRV1.88 и действительно не собралась на project rustc1.87: [исходный отказ](wave005/crypto/compile.log). Полный probe lock закрепляет `sha2=0.11.0`; `--locked` compile PASS. Отдельный `getrandom=0.4.3` probe ожидаемо [отказал на unsupported ARM target](wave005/crypto/entropy-unsupported.log), fake backend не добавлен. `rand_chacha` остаётся docs-only DRBG candidate. Старые NCC/Quarkslab audits не доказывают безопасность нынешнего полного dependency graph. Poly1305 требует constant-time multiplication; timing/compiler output на физическом PXA263 не измерены. Performance неизвестен, а не «достаточен по QEMU».

## Сохранённые регрессии и оставшиеся ограничения

Повторены Boot normal/panic, compile-only HaRET adapter и19 ROM-parser tests; E1 три TCG+три QTest; E2A boot/reset+четыре faults+QTest; E2B boot/reset+пять faults+QTest; UI24 tests/20000 deterministic operations; Wave004 три ARM boots,101 event и23 exact guest/host/QEMU framebuffer comparisons с нулевым pixel diff, display/input QTest и missing-reference negative regression. E1 сохраняет честный `PASS_WITH_RECORDED_MODEL_LIMITATIONS`: исторический timer state переживает reset. Прежние successful reports не перезаписаны; unchanged source/flat-image hashes проверены новым collector.

**Подтверждено источниками:** legacy ARMv5 MMU permissions/User modes, отсутствие современного XN, CPU260 functional model/cache limitations. **Проверено в ARM TCG:** перечисленные48 executions, аппаратные исключения, SVC return и kernel integrity. **Спроектировано:** future service/capability/crypto boundaries. **Неизвестно:** точное поведение PXA263 silicon/cache/TLB/errata/DMA, аппаратная энтропия, timing leakage, доверенный key provisioning и аппаратный root of trust/keystore/secure boot данного устройства. CPU MMU не изолирует DMA и не защищает от host QMP/loader; host/compiler/QEMU и privileged drivers входят в TCB.

Следующий небольшой этап: сохранить этот suite, определить bounded process lifetime/identity и timer preemption, затем расширять syscall ABI с rights/handle ownership и recoverable copy faults. Для UI — отдельный user-service/display broker contract, поскольку Wave004 ещё privileged. Для crypto — сначала entropy/key lifecycle/timing feasibility, затем готовая библиотека с конкретными негативными тестами. Реальные драйверы и физическая загрузка остаются отдельными рубежами.

## Воспроизведение

После подготовки закреплённых dependencies из [BUILDING.md](../BUILDING.md), используя существующий E2B cache:

```sh
scripts/build-security.sh
scripts/test-security.sh
# Вся принятая цепочка плюс security:
scripts/test-wave005.sh
# Текстовая evidence collection после успешного полного прогона:
python3 tools/collect_wave005_evidence.py --help
```

Фактический host — macOS x86_64, Rust `nightly-2025-03-01`/rustc1.87.0-nightly/LLVM20.1, пять прежних QEMU caches. На этом host задавались `RUSTUP_HOME` и существующие `QEMU_SYSTEM_ARM`, `QEMU_PXA`, `QEMU_BLUEANGEL`, `QEMU_E2B`, `QEMU_DISPLAY_TEST` согласно scripts; Linux/WSL2 в этой волне не исполнялся. Полные ELF/BIN/protocol logs остаются в ignored `target/artifacts`, публичный отчёт содержит очищенные текстовые evidence и hashes. OEM binaries, пользовательские данные и оригинальная firmware не публикуются.
