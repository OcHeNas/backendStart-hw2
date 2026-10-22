.PHONY: test install clean help

# Путь к Python
PYTHON := python3
PIP := pip3

# Папки
TEST_DIR := tests
VENV_DIR := .venv

help: ## Показать справку
	@echo "Доступные команды:"
	@echo "  install    - Установить зависимости для тестирования"
	@echo "  test       - Запустить основные тесты"
	@echo "  test SCHEDULE=1 - Запустить все тесты включая дополнительные"
	@echo "  clean      - Очистить временные файлы"
	@echo "  help       - Показать эту справку"

install: ## Установить зависимости
	@echo "🔧 Установка зависимостей..."
	@if command -v pip3 >/dev/null 2>&1; then \
		pip3 install --user -r requirements.txt 2>/dev/null || \
		pip3 install --break-system-packages -r requirements.txt 2>/dev/null || \
		echo "⚠️  Пропускаем установку зависимостей (возможны проблемы с цветным выводом)"; \
	else \
		echo "⚠️  pip3 не найден, пропускаем установку зависимостей"; \
	fi
	@echo "✅ Подготовка завершена"

test: install ## Запустить тесты
	@echo "🧪 Запуск тестов..."
	@if [ ! -f "compile.sh" ] || [ ! -f "execute.sh" ]; then \
		echo "❌ Отсутствуют необходимые скрипты compile.sh и execute.sh"; \
		echo "   Создайте скрипты согласно README.md"; \
		exit 1; \
	fi
	@if [ "$(SCHEDULE)" = "1" ]; then \
		echo "📋 Включены дополнительные тесты (SCHEDULE=1)"; \
		SCHEDULE=1 $(PYTHON) $(TEST_DIR)/tests.py; \
	else \
		echo "📋 Запуск основных тестов (используйте SCHEDULE=1 для дополнительных)"; \
		$(PYTHON) $(TEST_DIR)/tests.py; \
	fi
	@echo "✅ Все тесты прошли успешно!"

clean: ## Очистить временные файлы
	@echo "🧹 Очистка временных файлов..."
	rm -rf __pycache__ .pytest_cache *.pyc
	rm -f cryptoserver *.o *.out *.class
	rm -rf $(VENV_DIR)
	@echo "✅ Очистка завершена"