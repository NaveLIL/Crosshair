# Crosshair contributor instructions

Read README, HARDWARE, DECISIONS, BOOT and REVERSE_ENGINEERING first. Keep architecture-independent code, ARM entry, board support and drivers separate. Do not add placeholder subsystems instead of a tested result.

Local code/research/build/QEMU tests are allowed within an assigned task. Physical device execution, MMIO, modem commands, Flash/Radio/CID operations and physical SD writes need an explicitly authorized procedure. A connected PC is not device authorization.

Every technical conclusion identifies its source and address type (file offset, VA or PA). Distinguish implemented+tested, implemented+untested, source-confirmed, hypothesis and unknown. Emulator success is not Blue Angel hardware success.

Document unsafe/FFI contracts. Parsers check sizes/ranges and corrupted input; never execute extracted firmware. Retain third-party provenance/licenses. Do not commit ROM, device dumps, user data, credentials, personal images or machine-specific paths.

Before proposing a public update, run relevant tests and inspect the exact diff. [Publication policy](RIGHTS_AND_PUBLICATION.md). Own code is MIT; third-party source conditions remain separate.
