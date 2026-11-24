import shutil
from pathlib import Path

# ==========================================
# НАСТРОЙКИ МАППИНГА (ЧТО -> НА ЧТО МЕНЯЕМ)
# ==========================================
# Поддерживаются как однострочные, так и многострочные блоки.
# Используйте тройные кавычки """...""" для многострочного текста.
REPLACEMENTS = {
    # 1. Одна строка -> одна строка
    "DEBUG = True": "DEBUG = False",
    # 2. Одна строка -> несколько строк
    "# PLACEHOLDER_DB": """DB_HOST = '127.0.0.1'
DB_PORT = 5432
DB_NAME = 'production_db'""",
    # 3. Несколько строк -> одна строка
    """if old_flag:
    run_legacy_code()
    log('done')""": "run_new_code()",
    # 4. Несколько строк -> несколько строк
    """server {
    listen 80;
    server_name example.com;
}""": """server {
    listen 443 ssl;
    server_name example.com;
    ssl_certificate /etc/ssl/cert.pem;
}""",
}


def patch_document(
    file_path: str, mappings: dict[str, str], make_backup: bool = True
) -> None:
  path = Path(file_path)

  if not path.is_file():
    raise FileNotFoundError(f"Файл не найден: {path}")

  # Читаем файл (newline="" сохраняет оригинальные переводы строк при чтении)
  content = path.read_text(encoding="utf-8")

  # Определяем, какой перевод строк используется в файле (Windows \r\n или Linux/Mac \n)
  line_ending = "\r\n" if "\r\n" in content else "\n"

  # Приводим всё к стандартному \n для надёжного поиска и замены
  normalized_content = content.replace("\r\n", "\n")

  changes_count = 0
  for target, replacement in mappings.items():
    norm_target = target.replace("\r\n", "\n")
    norm_replacement = replacement.replace("\r\n", "\n")

    if norm_target in normalized_content:
      occurrences = normalized_content.count(norm_target)
      normalized_content = normalized_content.replace(
          norm_target, norm_replacement
      )
      changes_count += occurrences
      print(f"[OK] Найдено и заменено совпадений: {occurrences}")
    else:
      # Выводим первые 40 символов ненайденного блока для удобства отладки
      preview = norm_target.replace("\n", "\\n")[:40]
      print(f"[SKIP] Блок не найден: '{preview}...'")

  if changes_count == 0:
    print("Изменений не внесено. Файл не перезаписан.")
    return

  # Создаём бэкап перед перезаписью
  if make_backup:
    backup_path = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup_path)
    print(f"Резервная копия сохранена: {backup_path}")

  # Возвращаем исходный стиль переводов строк и сохраняем файл
  final_content = normalized_content.replace("\n", line_ending)
  path.write_text(final_content, encoding="utf-8")
  print(f"Файл успешно пропатчен: {path} (всего замен: {changes_count})")


if __name__ == "__main__":
  # Укажите путь к целевому файлу
  TARGET_FILE = "config.txt"

  patch_document(TARGET_FILE, REPLACEMENTS, make_backup=True)
