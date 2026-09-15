"""Console interface of SBS Bank (menu from the original project brief, extended).

Run: python -m sbs_bank.cli
"""

from __future__ import annotations

import getpass
from decimal import Decimal, InvalidOperation

from . import db
from .bank import BankService, OperationError, Session

MAIN_MENU = """
1. Créer un compte
2. Se connecter
0. Quitter"""

ACCOUNT_MENU = """
1. Consulter le solde
2. Ajouter des fonds
3. Effectuer un virement
4. Retirer des fonds
5. Clôturer le compte
6. Se déconnecter
0. Quitter"""


def read_amount(prompt: str) -> Decimal | None:
    raw = input(prompt).strip().replace(",", ".")
    try:
        return Decimal(raw).quantize(Decimal("0.01"))
    except InvalidOperation:
        print("Montant non reconnu.")
        return None


def account_loop(bank: BankService, session: Session) -> bool:
    """Return False when the user wants to quit the application."""
    while True:
        print(ACCOUNT_MENU)
        choice = input("> ").strip()
        try:
            if choice == "1":
                print(f"Solde : {bank.get_balance(session)} EUR")
            elif choice == "2":
                if (amount := read_amount("Montant à ajouter : ")) is not None:
                    bank.deposit(session, amount)
                    print("Fonds ajoutés.")
            elif choice == "3":
                target = input("Numéro de carte du bénéficiaire : ").strip()
                if (amount := read_amount("Montant à virer : ")) is not None:
                    bank.transfer(session, target, amount)
                    print("Virement effectué.")
            elif choice == "4":
                if (amount := read_amount("Montant à retirer : ")) is not None:
                    bank.withdraw(session, amount)
                    print("Retrait effectué.")
            elif choice == "5":
                paid_out = bank.close_account(session)
                print(f"Compte clôturé. Solde restitué : {paid_out} EUR")
                return True
            elif choice == "6":
                print("Vous êtes déconnecté.")
                return True
            elif choice == "0":
                return False
        except OperationError as error:
            print(error)


def main() -> None:
    conn = db.connect()
    bank = BankService(conn)
    try:
        while True:
            print(MAIN_MENU)
            choice = input("> ").strip()
            if choice == "1":
                first_name = input("Prénom : ")
                last_name = input("Nom : ")
                email = input("Email : ")
                card_number, pin = bank.create_account(first_name, last_name, email)
                print(f"\nVotre compte a été créé.\nNuméro de carte : {card_number}\nCode PIN : {pin}")
            elif choice == "2":
                card_number = input("Numéro de carte : ").strip()
                pin = getpass.getpass("Code PIN : ").strip()
                try:
                    session = bank.login(card_number, pin)
                except OperationError as error:
                    print(error)
                    continue
                print("Connexion réussie.")
                if not account_loop(bank, session):
                    break
            elif choice == "0":
                break
    finally:
        conn.close()
        print("Au revoir.")


if __name__ == "__main__":
    main()
