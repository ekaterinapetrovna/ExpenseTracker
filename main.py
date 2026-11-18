
import csv
import json
import math
from pathlib import Path
from datetime import datetime

import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from kivy_garden.matplotlib.backend_kivyagg import FigureCanvasKivyAgg

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.spinner import Spinner
from kivy.uix.scrollview import ScrollView
from kivy.uix.popup import Popup
from kivy.uix.image import Image

from firebase_config import (
    FIREBASE_API_KEY,
    FIREBASE_DATABASE_URL
)

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "transactions.json"
CSV_FILE = BASE_DIR / "transactions.csv"


Window.size = (480, 780)
Window.clearcolor = (1, 0.97, 0.98, 1)

DARK = (0.35, 0.18, 0.28, 1)
PINK = (0.75, 0.45, 0.60, 1)
ROSE = (0.65, 0.35, 0.50, 1)
DEEP_PINK = (0.55, 0.28, 0.43, 1)

CATEGORIES = (
    "Food", "Transport", "Shopping",
    "Rent", "Salary", "Sales", "Other"
)


def make_button(text, color=PINK):
    return Button(
        text=text,
        font_size=16,
        size_hint_y=None,
        height=46,
        background_normal="",
        background_color=color
    )


class ExpenseTrackerApp(App):

    def build(self):
        self.title = "ExpenseTracker"
        self.transactions = []
        self.id_token = None
        self.user_uid = None

        main_scroll = ScrollView()

        layout = BoxLayout(
            orientation="vertical",
            padding=18,
            spacing=9,
            size_hint_y=None
        )
        layout.bind(
            minimum_height=layout.setter("height")
        )

        layout.add_widget(Label(
            text="ExpenseTracker",
            font_size=28,
            bold=True,
            color=DARK,
            size_hint_y=None,
            height=50
        ))

        layout.add_widget(Label(
            text="Income and Expense Tracker",
            font_size=15,
            color=DARK,
            size_hint_y=None,
            height=28
        ))

        self.balance_label = Label(
            text="Balance: 0.00 RUB",
            font_size=23,
            bold=True,
            color=DARK,
            size_hint_y=None,
            height=65
        )
        layout.add_widget(self.balance_label)

        self.amount_input = TextInput(
            hint_text="Enter amount (RUB)",
            multiline=False,
            input_filter="float",
            font_size=18,
            size_hint_y=None,
            height=46
        )
        layout.add_widget(self.amount_input)

        self.category_spinner = Spinner(
            text="Select category",
            values=CATEGORIES,
            font_size=16,
            size_hint_y=None,
            height=46,
            background_normal="",
            background_color=PINK
        )
        layout.add_widget(self.category_spinner)

        income_button = make_button("Add Income")
        income_button.bind(
            on_press=lambda instance:
            self.add_transaction("Income")
        )
        layout.add_widget(income_button)

        expense_button = make_button(
            "Add Expense", ROSE
        )
        expense_button.bind(
            on_press=lambda instance:
            self.add_transaction("Expense")
        )
        layout.add_widget(expense_button)

        analytics_button = make_button(
            "Show Analytics", DEEP_PINK
        )
        analytics_button.bind(
            on_press=self.show_analytics
        )
        layout.add_widget(analytics_button)

        export_button = make_button("Export CSV")
        export_button.bind(on_press=self.export_csv)
        layout.add_widget(export_button)

        layout.add_widget(Label(
            text="Firebase Cloud Synchronization",
            font_size=19,
            bold=True,
            color=DARK,
            size_hint_y=None,
            height=40
        ))

        login_button = make_button(
            "Login to Firebase", DEEP_PINK
        )
        login_button.bind(on_press=self.show_login)
        layout.add_widget(login_button)

        upload_button = make_button("Upload to Cloud")
        upload_button.bind(
            on_press=self.confirm_upload
        )
        layout.add_widget(upload_button)

        download_button = make_button(
            "Download from Cloud", ROSE
        )
        download_button.bind(
            on_press=self.confirm_download
        )
        layout.add_widget(download_button)

        self.message_label = Label(
            text="",
            font_size=13,
            color=ROSE,
            size_hint_y=None,
            height=42
        )
        layout.add_widget(self.message_label)

        layout.add_widget(Label(
            text="Transaction History",
            font_size=20,
            bold=True,
            color=DARK,
            size_hint_y=None,
            height=40
        ))

        self.history_layout = BoxLayout(
            orientation="vertical",
            spacing=6,
            size_hint_y=None
        )
        self.history_layout.bind(
            minimum_height=self.history_layout.setter("height")
        )

        layout.add_widget(self.history_layout)
        main_scroll.add_widget(layout)

        self.load_transactions()
        return main_scroll

    def show_message(self, text):
        self.message_label.text = text

    def validate_transactions(self, data):
        if not isinstance(data, list):
            raise ValueError("Invalid transaction list")

        result = []

        for item in data:
            if not isinstance(item, dict):
                raise ValueError("Invalid transaction")

            kind = item.get("type")
            category = item.get("category")
            amount = float(item.get("amount"))

            if kind not in ("Income", "Expense"):
                raise ValueError("Invalid type")

            if not isinstance(category, str):
                raise ValueError("Invalid category")

            if not math.isfinite(amount) or amount <= 0:
                raise ValueError("Invalid amount")

            result.append({
                "type": kind,
                "category": category,
                "amount": amount,
                "date": str(item.get("date", ""))
            })

        return result

    def refresh_history(self):
        self.history_layout.clear_widgets()

        for transaction in reversed(self.transactions):
            sign = (
                "+" if transaction["type"] == "Income"
                else "-"
            )

            self.history_layout.add_widget(Label(
                text=(
                    f"{sign}{transaction['amount']:.2f} "
                    f"RUB | {transaction['category']}"
                ),
                font_size=15,
                color=DARK,
                size_hint_y=None,
                height=36
            ))

        balance = sum(
            t["amount"] if t["type"] == "Income"
            else -t["amount"]
            for t in self.transactions
        )

        self.balance_label.text = (
            f"Balance: {balance:.2f} RUB"
        )

    def add_transaction(self, kind):
        try:
            amount = round(
                float(self.amount_input.text.strip()), 2
            )
        except ValueError:
            self.show_message("Please enter a valid amount.")
            return

        if not math.isfinite(amount) or amount <= 0:
            self.show_message("Enter a positive amount.")
            return

        category = self.category_spinner.text

        if category == "Select category":
            self.show_message("Please select a category.")
            return

        transaction = {
            "type": kind,
            "amount": amount,
            "category": category,
            "date": datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        }

        self.transactions.append(transaction)

        if self.save_transactions():
            self.refresh_history()
            self.amount_input.text = ""
            self.category_spinner.text = "Select category"
            self.show_message("Transaction added!")

    def save_transactions(self):
        try:
            with open(
                DATA_FILE, "w", encoding="utf-8"
            ) as file:
                json.dump(
                    self.transactions,
                    file,
                    ensure_ascii=False,
                    indent=4
                )
            return True
        except OSError as error:
            self.show_message(f"Save error: {error}")
            return False

    def load_transactions(self):
        if not DATA_FILE.exists():
            self.refresh_history()
            return

        try:
            with open(
                DATA_FILE, "r", encoding="utf-8"
            ) as file:
                data = json.load(file)

            self.transactions = (
                self.validate_transactions(data)
            )
            self.refresh_history()

        except (OSError, ValueError, TypeError) as error:
            self.show_message(f"Load error: {error}")

    def export_csv(self, instance):
        if not self.transactions:
            self.show_message("No transactions to export.")
            return

        try:
            with open(
                CSV_FILE,
                "w",
                newline="",
                encoding="utf-8-sig"
            ) as file:
                writer = csv.writer(
                    file, delimiter=";"
                )
                writer.writerow([
                    "Date", "Type",
                    "Category", "Amount (RUB)"
                ])

                for item in self.transactions:
                    writer.writerow([
                        item.get("date", ""),
                        item["type"],
                        item["category"],
                        item["amount"]
                    ])

            self.show_message(
                "CSV exported successfully!"
            )

        except OSError as error:
            self.show_message(f"CSV error: {error}")

    def show_analytics(self, instance):
        if not self.transactions:
            self.show_message("No data for analytics.")
            return

        income = sum(
            t["amount"]
            for t in self.transactions
            if t["type"] == "Income"
        )

        expenses = sum(
            t["amount"]
            for t in self.transactions
            if t["type"] == "Expense"
        )

        categories = {}

        for item in self.transactions:
            if item["type"] == "Expense":
                category = item["category"]
                categories[category] = (
                    categories.get(category, 0)
                    + item["amount"]
                )

        fig, axes = plt.subplots(
            2, 1, figsize=(7, 9)
        )
        fig.patch.set_facecolor("#fff7fa")

        if categories:
            axes[0].pie(
                list(categories.values()),
                labels=list(categories.keys()),
                autopct="%1.1f%%",
                colors=[
                    "#b87598", "#d99bb9",
                    "#e6bfd1", "#965675"
                ]
            )
            axes[0].set_title(
                "Expenses by Category",
                color="#593047",
                fontweight="bold"
            )
        else:
            axes[0].text(
                0.5, 0.5, "No expenses yet",
                ha="center", va="center"
            )
            axes[0].axis("off")

        axes[1].bar(
            ["Income", "Expenses"],
            [income, expenses],
            color=["#b87598", "#965675"]
        )
        axes[1].set_title(
            "Income vs Expenses",
            color="#593047",
            fontweight="bold"
        )
        axes[1].set_ylabel("Amount (RUB)")
        axes[1].set_ylim(
            0, max(income, expenses, 1) * 1.2
        )

        fig.tight_layout()

        content = BoxLayout(
            orientation="vertical",
            padding=10,
            spacing=10
        )

        chart = FigureCanvasKivyAgg(fig)
        content.add_widget(chart)

        popup = Popup(
            title="ExpenseTracker Analytics",
            content=content,
            size_hint=(0.95, 0.9)
        )

        close_button = make_button("Close")
        close_button.bind(on_press=popup.dismiss)
        content.add_widget(close_button)

        popup.open()

    def show_login(self, instance):
        content = BoxLayout(
            orientation="vertical",
            padding=15,
            spacing=10
        )

        email_input = TextInput(
            hint_text="Firebase email",
            multiline=False,
            size_hint_y=None,
            height=45
        )

        password_input = TextInput(
            hint_text="Firebase password",
            password=True,
            multiline=False,
            size_hint_y=None,
            height=45
        )

        content.add_widget(email_input)
        content.add_widget(password_input)

        login_button = make_button("Login")
        cancel_button = make_button("Cancel", ROSE)

        content.add_widget(login_button)
        content.add_widget(cancel_button)

        popup = Popup(
            title="Firebase Login",
            content=content,
            size_hint=(0.9, None),
            height=300
        )

        def login_action(instance):
            email = email_input.text.strip()
            password = password_input.text

            if not email or not password:
                self.show_message(
                    "Enter email and password."
                )
                return

            popup.dismiss()
            password_input.text = ""
            self.login_firebase(email, password)

        login_button.bind(on_press=login_action)
        cancel_button.bind(on_press=popup.dismiss)

        popup.open()

    def login_firebase(self, email, password):
        self.show_message("Connecting to Firebase...")

        url = (
            "https://identitytoolkit.googleapis.com/v1/"
            "accounts:signInWithPassword"
        )

        try:
            response = requests.post(
                url,
                params={"key": FIREBASE_API_KEY},
                json={
                    "email": email,
                    "password": password,
                    "returnSecureToken": True
                },
                timeout=15
            )

            response.raise_for_status()
            result = response.json()

            self.id_token = result["idToken"]
            self.user_uid = result["localId"]

            self.show_message(
                "Firebase login successful!"
            )

        except (requests.RequestException,
                ValueError, KeyError):
            self.id_token = None
            self.user_uid = None
            self.show_message(
                "Firebase login failed. Check credentials."
            )

    def cloud_url(self):
        base = FIREBASE_DATABASE_URL.rstrip("/")
        return (
            f"{base}/users/{self.user_uid}/"
            "transactions.json"
        )

    def confirm_upload(self, instance):
        if not self.id_token:
            self.show_message("Login to Firebase first.")
            return

        if not self.transactions:
            self.show_message("No transactions to upload.")
            return

        self.confirm_action(
            "Upload to Cloud",
            "Replace cloud data with local transactions?",
            self.upload_cloud
        )

    def confirm_download(self, instance):
        if not self.id_token:
            self.show_message("Login to Firebase first.")
            return

        self.confirm_action(
            "Download from Cloud",
            "Replace local transactions with cloud data?",
            self.download_cloud
        )

    def confirm_action(self, title, question, callback):
        content = BoxLayout(
            orientation="vertical",
            padding=12,
            spacing=10
        )

        content.add_widget(Label(
            text=question,
            font_size=14
        ))

        yes_button = make_button("Yes")
        no_button = make_button("Cancel", ROSE)

        content.add_widget(yes_button)
        content.add_widget(no_button)

        popup = Popup(
            title=title,
            content=content,
            size_hint=(0.9, None),
            height=240
        )

        def confirm(instance):
            popup.dismiss()
            callback()

        yes_button.bind(on_press=confirm)
        no_button.bind(on_press=popup.dismiss)
        popup.open()

    def upload_cloud(self):
        self.show_message("Uploading to Firebase...")

        try:
            response = requests.put(
                self.cloud_url(),
                params={"auth": self.id_token},
                json=self.transactions,
                timeout=15
            )
            response.raise_for_status()

            self.show_message(
                "Cloud upload successful!"
            )

        except requests.RequestException as error:
            self.show_message(
                f"Cloud upload failed: {error}"
            )

    def download_cloud(self):
        self.show_message("Downloading from Firebase...")

        try:
            response = requests.get(
                self.cloud_url(),
                params={"auth": self.id_token},
                timeout=15
            )
            response.raise_for_status()

            data = response.json()

            if data is None:
                self.show_message(
                    "No cloud transactions found."
                )
                return

            validated = self.validate_transactions(data)

            # Save a backup before replacing local data.
            if DATA_FILE.exists():
                backup = BASE_DIR / "transactions_before_cloud.json"
                backup.write_bytes(DATA_FILE.read_bytes())

            self.transactions = validated

            if self.save_transactions():
                self.refresh_history()
                self.show_message(
                    "Cloud download successful!"
                )

        except (
            requests.RequestException,
            ValueError,
            TypeError,
            OSError
        ) as error:
            self.show_message(
                f"Cloud download failed: {error}"
            )


if __name__ == "__main__":
    ExpenseTrackerApp().run()
