from __future__ import annotations


def print_header(title: str, subtitle: str | None = None) -> None:
    print("\n" + "=" * 72)
    print(title)
    if subtitle:
        print(subtitle)
    print("=" * 72)


def prompt_text(message: str, default: str | None = None, allow_empty: bool = False) -> str:
    while True:
        suffix = f" [{default}]" if default is not None else ""
        value = input(f"{message}{suffix}: ").strip()
        if not value and default is not None:
            return default
        if value or allow_empty:
            return value
        print("Introduce un valor valido.")


def prompt_int(message: str, default: int | None = None, minimum: int | None = None) -> int:
    while True:
        suffix = f" [{default}]" if default is not None else ""
        raw = input(f"{message}{suffix}: ").strip()
        if not raw and default is not None:
            value = default
        else:
            try:
                value = int(raw)
            except ValueError:
                print("Introduce un numero entero.")
                continue
        if minimum is not None and value < minimum:
            print(f"El valor minimo es {minimum}.")
            continue
        return value


def prompt_float(message: str, default: float | None = None, minimum: float | None = None) -> float:
    while True:
        suffix = f" [{default}]" if default is not None else ""
        raw = input(f"{message}{suffix}: ").strip()
        if not raw and default is not None:
            value = default
        else:
            try:
                value = float(raw.replace(",", "."))
            except ValueError:
                print("Introduce un numero valido.")
                continue
        if minimum is not None and value < minimum:
            print(f"El valor minimo es {minimum}.")
            continue
        return value


def prompt_yes_no(message: str, default: bool = True) -> bool:
    default_label = "S/n" if default else "s/N"
    while True:
        raw = input(f"{message} [{default_label}]: ").strip().lower()
        if not raw:
            return default
        if raw in {"s", "si", "sí", "y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("Responde s o n.")


def prompt_choice(message: str, options: list[str], default: int = 0) -> str:
    while True:
        print(f"\n{message}")
        for index, option in enumerate(options, start=1):
            label = " (recomendado)" if index - 1 == default else ""
            print(f"  {index}. {option}{label}")
        raw = input(f"Selecciona una opcion [{default + 1}]: ").strip()
        if not raw:
            return options[default]
        try:
            selected = int(raw) - 1
        except ValueError:
            print("Seleccion no valida.")
            continue
        if 0 <= selected < len(options):
            return options[selected]
        print("Seleccion no valida.")


def prompt_int_list(message: str, default: list[int] | None = None) -> list[int]:
    default_text = ",".join(str(value) for value in default) if default else None
    while True:
        suffix = f" [{default_text}]" if default_text is not None else ""
        raw = input(f"{message}{suffix}: ").strip()
        if not raw and default is not None:
            return default
        try:
            values = [int(token.strip()) for token in raw.split(",") if token.strip()]
        except ValueError:
            print("Usa una lista de enteros separados por comas.")
            continue
        if values:
            return values
        print("Introduce al menos un ID.")
