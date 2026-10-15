# Портативний офлайн-набір на USB-накопичувачі

[English](../en/portable.md) · [Зміст документації](README.md)

Розгортання Ковчега — це одна тека. Підготуйте її один раз на комп'ютері з доступом до інтернету, скопіюйте на USB-накопичувач або SSD і запускайте на будь-якому комп'ютері з тією самою операційною системою та архітектурою процесора — без інтернету й без прав адміністратора.

```
KOVCHEG/
├── kovcheg.toml          налаштування (почніть з examples/tier-*.toml)
├── models/               завантажені моделі (див. models.md)
├── modules/              зібрані модулі (бази знань)
├── keys/trusted/         відкриті ключі авторів модулів, яким ви довіряєте
├── wheelhouse/           пакети Python для офлайн-встановлення
├── src/, pyproject.toml  сам Ковчег (копія цього репозиторію)
├── kovcheg.sh            запускач для Linux / macOS
└── kovcheg.bat           запускач для Windows
```

## 1. Підготовка (онлайн, на тій самій ОС і архітектурі, що й цільовий комп'ютер)

```bash
git clone https://github.com/sashapiscivca-svg/Kovcheg KOVCHEG && cd KOVCHEG
cp examples/tier-a-minipc.toml kovcheg.toml                     # або tier-s / tier-b
# Linux: PyTorch лише для CPU робить набір компактним
python3 -m pip download -d wheelhouse torch --index-url https://download.pytorch.org/whl/cpu
python3 -m pip download -d wheelhouse ".[docs,ui,sign,embed,llm]" setuptools wheel   # setuptools: потрібен, щоб установити сам Ковчег офлайн
```

Завантажте моделі в `models/` ([models.md](models.md)) і зберіть свої модулі (`kovcheg build ...`) або скопіюйте в `modules/` модулі, зібрані деінде.

Під час `pip download` пакет `llama-cpp-python` може збиратися з вихідного коду. У такому разі завантажений файл буде архівом вихідного коду, і на цільовому комп'ютері знадобиться компілятор. Щоб цього уникнути, зберіть wheel-пакет на комп'ютері для підготовки (`pip wheel llama-cpp-python -w wheelhouse`) і скопіюйте його.

## 2. Установлення на цільовому комп'ютері (офлайн)

На цільовому комп'ютері потрібен Python 3.11 або новіший. Windows: установіть його з python.org для поточного користувача — для цього не потрібні права адміністратора. Більшість дистрибутивів Linux уже його містять.

```bash
cd /media/usb/KOVCHEG
python3 -m venv .venv
.venv/bin/pip install --no-index --find-links wheelhouse -e ".[docs,ui,sign,embed,llm]"
```

Windows: `py -3 -m venv .venv` і `.venv\Scripts\pip install --no-index --find-links wheelhouse -e ".[docs,ui,sign,embed,llm]"`.

## 3. Запуск

`kovcheg.sh` і `kovcheg.bat` задають `KOVCHEG_HOME` як теку набору й запускають вебінтерфейс:

```bash
./kovcheg.sh            # те саме, що: KOVCHEG_HOME=$PWD .venv/bin/kovcheg ui
./kovcheg.sh doctor     # далі може йти будь-яка команда kovcheg
```

## Поради для польового використання

- **Перевірте набір на цільовому обладнанні заздалегідь, до того як він знадобиться.** Запустіть `kovcheg doctor` і поставте кілька типових запитань.
- Майте **резервний режим «лише пошук»**: якщо на комп'ютері замало оперативної пам'яті, запускайте `kovcheg ui`, задавши `[llm] model = ""` і `[embedding] model = ""` (BM25 не потребує моделей, а модулі, зібрані з енкодером, однаково працюють: їхній повнотекстовий індекс є завжди).
- USB-накопичувачі стандарту USB 2.0 повільні. Завантаження моделі на 2,3 ГБ може тривати хвилину, тож за можливості копіюйте набір на внутрішній диск.
- Тримайте другу копію набору та надрукований список документів, які він містить.
