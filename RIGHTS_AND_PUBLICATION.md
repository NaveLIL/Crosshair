# Публичные материалы и лицензия

Собственный код Crosshair распространяется по [MIT License](LICENSE), copyright 2026 NaveLIL. Этот файл LICENSE уже существовал в публичном репозитории и сохраняется без изменения. MIT не перелицензирует сторонние исходники, ROM, шрифты, графику или данные.

QEMU, HaRET и исторические Linux/PXADroid sources сохраняют собственные copyright/license notices. Проект ссылается на первоисточники и хеши; сторонние бинарники и полные reference trees не включены. Перенос реализации требует отдельной фиксации происхождения и совместимых условий.

Системные значки Shell основаны на18 исходных SVG [Tabler Icons](https://github.com/tabler/tabler-icons), pinned commit `a4ce1404bc6d24d3c365afe7b258d6bf6f48d62d`. Сохранены оригинальная [MIT-лицензия Paweł Kuna](shell/assets/tabler/LICENSE), [происхождение и хеши](shell/assets/tabler/PROVENANCE.json); производные bitmap masks сохраняют это указание. Собственный генератор — project MIT. [Cozette](ui/third_party/cozette/LICENSE) сохраняет отдельную лицензию шрифта. Утверждённый владельцем [визуальный reference](docs/UI_DESIGN_SYSTEM.md#approved-visual-reference-for-crosshair-shell-01) не получает лицензию Tabler или шрифта.

Обои Wave007.1 — отдельный пейзаж, созданный для Crosshair встроенным imagegen по художественному направлению владельца. [Исходный PNG, prompt и provenance](shell/assets/wallpaper/PROVENANCE.json) сохранены; в него не включены нарисованные элементы интерфейса. Это не фотография устройства, OEM resource или копия обоев из ROM. Условия проектного ресурса указаны в provenance отдельно от прав на утверждённый reference; runtime использует только подготовленные compact RGB565 данные.

В поставку не входят ROM/radio/bootloader binaries, фотографии и личные истории, пользовательские дампы, VM, установщики Windows, лицензирующие ключи, SIM/IMEI/контакты. Технические ROM file catalogs и hashes не являются публикацией самих бинарников.

Первоначальный публичный снимок сформирован явным allowlist через `scripts/export-public.py` в отдельный checkout публичного origin/main. Дальнейшая разработка E2A/UI ведётся в этом чистом публичном checkout; старый export audit относится к принятому foundation snapshot. Локальная приватная история Git не переносится. Отчёты с нормализованными host paths обозначены как presentation copies; хеши guest outputs сохраняют исходное значение. [Export audit](reports/public-export-audit.json).

E2A host overlay имеет отдельную GPL-2.0-only область с сохранёнными notices и [полной лицензией](crosshair-emulator/qemu/COPYING.GPL-2.0). Это host QEMU code, не часть MIT ядра. Для новой волны проверяются точный Git diff, лицензионные границы и текстовые evidence; собственные исполняемые образы остаются локальными результатами воспроизводимой сборки.
