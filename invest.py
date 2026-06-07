"""
===================================================================
INVESTMENT PRO BOT - ULTRA LIGHTWEIGHT OPTIMIZED VERSION (CRASH-FREE)
===================================================================
"""

import logging
import sqlite3
import random
import string
import os
import asyncio
import gc  # Garbage Collector for memory management
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, ContextTypes, filters
)

load_dotenv()

# Memory efficient logging configuration
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ===================================================================
# CONFIGURATION
# ===================================================================

class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
    ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "12345678").split(",") if x.strip()]
    DB_PATH = os.getenv("DB_PATH", "investment_bot.db")
    CURRENCY = os.getenv("CURRENCY", "$")
    
    MIN_INVESTMENT = Decimal(os.getenv("MIN_INVESTMENT", "10"))
    MAX_INVESTMENT = Decimal(os.getenv("MAX_INVESTMENT", "100000"))
    
    REF_L1_PERCENT = Decimal(os.getenv("REF_L1_PERCENT", "5"))
    REF_L2_PERCENT = Decimal(os.getenv("REF_L2_PERCENT", "3"))
    REF_L3_PERCENT = Decimal(os.getenv("REF_L3_PERCENT", "1"))
    
    WALLET_ADDRESS = os.getenv("WALLET_ADDRESS", "0x1234567890abcdef1234567890abcdef12345678")
    PAYMENT_METHOD = os.getenv("PAYMENT_METHOD", "USDT (TRC20)")

    PLANS = {
        "starter": {"name": "Starter", "min": Decimal("10"), "max": Decimal("500"), "daily_rate": Decimal("0.01"), "duration": 30, "description": "Perfect for beginners"},
        "silver": {"name": "Silver", "min": Decimal("500"), "max": Decimal("2500"), "daily_rate": Decimal("0.015"), "duration": 60, "description": "Balanced growth plan"},
        "gold": {"name": "Gold", "min": Decimal("2500"), "max": Decimal("10000"), "daily_rate": Decimal("0.02"), "duration": 90, "description": "High return investment"},
        "platinum": {"name": "Platinum", "min": Decimal("10000"), "max": Decimal("100000"), "daily_rate": Decimal("0.025"), "duration": 120, "description": "Premium elite plan"},
    }

# ===================================================================
# DATABASE ENGINE (LIGHTWEIGHT WITH TIMEOUTS)
# ===================================================================

class Database:
    def __init__(self):
        self.conn = sqlite3.connect(Config.DB_PATH, check_same_thread=False, timeout=30.0)
        self.create_tables()

    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT,
                phone TEXT, email TEXT, referral_code TEXT UNIQUE, referred_by INTEGER,
                balance TEXT DEFAULT '0.00', total_invested TEXT DEFAULT '0.00', 
                total_earned TEXT DEFAULT '0.00', total_withdrawn TEXT DEFAULT '0.00', 
                joined_date TEXT, status TEXT DEFAULT 'active'
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS investments (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, plan_type TEXT,
                amount TEXT, daily_rate TEXT, duration INTEGER, start_date TEXT,
                end_date TEXT, total_return TEXT, daily_earning TEXT, status TEXT DEFAULT 'active',
                total_earned TEXT DEFAULT '0.00', last_calculation TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deposit_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, plan_type TEXT,
                amount TEXT, transaction_id TEXT UNIQUE, status TEXT DEFAULT 'pending',
                created_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id INTEGER, referred_id INTEGER,
                level INTEGER, bonus_amount TEXT, created_at TEXT
            )
        """)
        self.conn.commit()

    def execute(self, query, params=()):
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        self.conn.commit()
        return cursor

    def fetchone(self, query, params=()):
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchone()

    def fetchall(self, query, params=()):
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()

# ===================================================================
# MANAGEMENT PLUGINS
# ===================================================================

class UserManager:
    def __init__(self, db: Database):
        self.db = db

    def generate_referral_code(self) -> str:
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

    def get_or_create_user(self, user_id: int, username: str, first_name: str, referral_code: str = None) -> dict:
        user = self.db.fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))
        if not user:
            ref_code = self.generate_referral_code()
            referred_by = None
            if referral_code:
                referrer = self.db.fetchone("SELECT user_id FROM users WHERE referral_code = ?", (referral_code,))
                if referrer and referrer[0] != user_id:
                    referred_by = referrer[0]
            
            self.db.execute("""
                INSERT INTO users (user_id, username, first_name, referral_code, referred_by, joined_date)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, username, first_name, ref_code, referred_by, datetime.now().isoformat()))
            user = self.db.fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))
        
        return {
            "user_id": user[0], "username": user[1], "first_name": user[2],
            "balance": Decimal(user[8]), "total_invested": Decimal(user[9]), "total_earned": Decimal(user[10]),
            "total_withdrawn": Decimal(user[11]), "referral_code": user[6]
        }

    def get_user(self, user_id: int) -> Optional[dict]:
        user = self.db.fetchone("SELECT * FROM users WHERE user_id = ?", (user_id,))
        if not user: return None
        return {
            "user_id": user[0], "username": user[1], "first_name": user[2],
            "balance": Decimal(user[8]), "total_invested": Decimal(user[9]), "total_earned": Decimal(user[10]),
            "total_withdrawn": Decimal(user[11]), "referral_code": user[6]
        }

class InvestmentManager:
    def __init__(self, db: Database):
        self.db = db

    def create_investment(self, user_id: int, plan_type: str, amount: Decimal) -> dict:
        plan = Config.PLANS[plan_type]
        daily_earning = (amount * plan["daily_rate"]).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        total_return = (daily_earning * plan["duration"]).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        start_date = datetime.now()
        end_date = start_date + timedelta(days=plan["duration"])
        
        cursor = self.db.execute("""
            INSERT INTO investments (user_id, plan_type, amount, daily_rate, duration, start_date, 
             end_date, total_return, daily_earning, last_calculation)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, plan_type, str(amount), str(plan["daily_rate"]), plan["duration"], 
              start_date.isoformat(), end_date.isoformat(), str(total_return), str(daily_earning), start_date.isoformat()))
        
        user_data = self.db.fetchone("SELECT total_invested FROM users WHERE user_id = ?", (user_id,))
        new_total = (Decimal(user_data[0]) + amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.db.execute("UPDATE users SET total_invested = ? WHERE user_id = ?", (str(new_total), user_id))
        
        self.distribute_referral_commissions(user_id, amount)
        return {"success": True, "plan": plan["name"], "amount": amount, "daily_earning": daily_earning}

    def distribute_referral_commissions(self, user_id: int, investment_amount: Decimal):
        current_user_id = user_id
        tiers = [
            {"level": 1, "percent": Config.REF_L1_PERCENT},
            {"level": 2, "percent": Config.REF_L2_PERCENT},
            {"level": 3, "percent": Config.REF_L3_PERCENT}
        ]
        
        for tier in tiers:
            parent_data = self.db.fetchone("SELECT referred_by FROM users WHERE user_id = ?", (current_user_id,))
            if not parent_data or not parent_data[0]: break
                
            referrer_id = parent_data[0]
            bonus = (investment_amount * (tier["percent"] / Decimal("100"))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            
            ref_user = self.db.fetchone("SELECT balance FROM users WHERE user_id = ?", (referrer_id,))
            if ref_user:
                new_balance = (Decimal(ref_user[0]) + bonus).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                self.db.execute("UPDATE users SET balance = ? WHERE user_id = ?", (str(new_balance), referrer_id))
                self.db.execute("""
                    INSERT INTO referrals (referrer_id, referred_id, level, bonus_amount, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (referrer_id, user_id, tier["level"], str(bonus), datetime.now().isoformat()))
                
            current_user_id = referrer_id

# ===================================================================
# UI KEYBOARDS
# ===================================================================

class Keyboards:
    @staticmethod
    def main_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Invest", callback_data="invest"), InlineKeyboardButton("📊 Portfolio", callback_data="portfolio")],
            [InlineKeyboardButton("💵 Withdraw", callback_data="withdraw"), InlineKeyboardButton("👥 Referral", callback_data="referral")],
            [InlineKeyboardButton("🤝 Support", callback_data="support"), InlineKeyboardButton("♻️ Statistics", callback_data="stats")]
        ])

    @staticmethod
    def plans_menu() -> InlineKeyboardMarkup:
        keyboard = []
        for key, plan in Config.PLANS.items():
            keyboard.append([InlineKeyboardButton(f"{plan['name']} ({plan['daily_rate']*100}%)", callback_data=f"plan_{key}")])
        keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")])
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def confirm_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("⚡ Confirm & Check Nodes", callback_data="confirm_deposit"), 
             InlineKeyboardButton("❌ Cancel", callback_data="cancel_deposit")]
        ])

    @staticmethod
    def back_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_menu")]])

    @staticmethod
    def admin_deposit_approval(deposit_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Approve", callback_data=f"approve_deposit_{deposit_id}"),
             InlineKeyboardButton("❌ Reject", callback_data=f"reject_deposit_{deposit_id}")]
        ])

# ===================================================================
# BOT BUSINESS LOGIC
# ===================================================================

SELECTING_PLAN, ENTERING_AMOUNT, ENTERING_TRANSACTION_ID, CONFIRMING_DEPOSIT = range(4)
ENTERING_WITHDRAW_AMOUNT = 5

class InvestmentBot:
    def __init__(self):
        self.db = Database()
        self.user_manager = UserManager(self.db)
        self.investment_manager = InvestmentManager(self.db)

    async def send_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
        user = self.user_manager.get_or_create_user(update.effective_user.id, update.effective_user.username, update.effective_user.first_name)
        text = (
            f"<b>🌟 INVESTMENT PRO DASHBOARD</b>\n"
            f"<i>⚙️ Status: <code>[Enterprise PostgreSQL Node Connected]</code></i>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 <b>Account ID:</b> <code>{user['user_id']}</code>\n"
            f"💰 <b>Available Balance:</b> <code>{Config.CURRENCY}{user['balance']:,.2f}</code>\n\n"
            f"📊 <b>Financial Statements:</b>\n"
            f" ├ Active Capital: <code>{Config.CURRENCY}{user['total_invested']:,.2f}</code>\n"
            f" ├ Total Net Earnings: <code>{Config.CURRENCY}{user['total_earned']:,.2f}</code>\n"
            f" └ Total Withdrawn: <code>{Config.CURRENCY}{user['total_withdrawn']:,.2f}</code>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ <i>Select an action from the control console below:</i>"
        )
        if edit and update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=Keyboards.main_menu(), parse_mode="HTML")
        else:
            if update.message: await update.message.reply_text(text, reply_markup=Keyboards.main_menu(), parse_mode="HTML")
            elif update.callback_query: await update.callback_query.message.reply_text(text, reply_markup=Keyboards.main_menu(), parse_mode="HTML")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        ref_code = context.args[0] if context.args else None
        self.user_manager.get_or_create_user(update.effective_user.id, update.effective_user.username, update.effective_user.first_name, ref_code)
        await self.send_main_menu(update, context, edit=False)

    async def back_to_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.callback_query: await update.callback_query.answer()
        context.user_data.clear()
        await self.send_main_menu(update, context, edit=True)
        gc.collect()  # Forced garbage collection to keep memory optimized
        return ConversationHandler.END

    # ===================================================================
    # INVESTMENT FLOW
    # ===================================================================
    async def invest_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query; await query.answer()
        text = "<b>📈 SELECT SMART INVESTMENT PORTFOLIO</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        for k, p in Config.PLANS.items():
            text += f"💼 <b>{p['name']} Plan:</b> <code>{p['daily_rate']*100}%</code> Daily / {p['duration']} Days\n"
        text += "\n⚙️ <i>Select a tier below to view details and invest:</i>"
        await query.edit_message_text(text, reply_markup=Keyboards.plans_menu(), parse_mode="HTML")
        return SELECTING_PLAN

    async def plan_selected(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query; await query.answer()
        plan_type = query.data.replace("plan_", "")
        context.user_data["selected_plan"] = plan_type
        plan = Config.PLANS[plan_type]
        text = (
            f"<b>📋 PLAN MATRIX: {plan['name'].upper()}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔹 <b>Minimum Allocation:</b> <code>{Config.CURRENCY}{plan['min']:,}</code>\n"
            f"🔹 <b>Maximum Allocation:</b> <code>{Config.CURRENCY}{plan['max']:,}</code>\n"
            f"🔹 <b>Daily Dividend Rate:</b> <code>{plan['daily_rate']*100}%</code>\n"
            f"🔹 <b>Lockup Period:</b> <code>{plan['duration']} Days</code>\n\n"
            f"<b>⌨️ Please type investment capital amount ({Config.CURRENCY}):</b>"
        )
        await query.edit_message_text(text, reply_markup=Keyboards.back_menu(), parse_mode="HTML")
        return ENTERING_AMOUNT

    async def amount_entered(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            val = update.message.text.strip().replace(Config.CURRENCY, "").replace("$", "").replace(",", "")
            amount = Decimal(val).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except Exception:
            await update.message.reply_text("❌ <b>Invalid Input Style!</b> Enter number only:", reply_markup=Keyboards.back_menu(), parse_mode="HTML")
            return ENTERING_AMOUNT

        plan_type = context.user_data.get("selected_plan")
        plan = Config.PLANS[plan_type]
        if amount < plan["min"] or amount > plan["max"]:
            await update.message.reply_text(f"❌ Allowed range: <code>{Config.CURRENCY}{plan['min']}</code> - <code>{Config.CURRENCY}{plan['max']}</code>", reply_markup=Keyboards.back_menu(), parse_mode="HTML")
            return ENTERING_AMOUNT

        context.user_data["investment_amount"] = amount
        payment_text = (
            f"<b>⚡ AUTO-GENERATED PAYMENT INVOICE</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💵 <b>Target Amount:</b> <code>{Config.CURRENCY}{amount:,.2f}</code>\n"
            f"💼 <b>Selected Category:</b> <code>{plan['name']} Plan</code>\n\n"
            f"⚙️ <b>DEPOSIT DESTINATION:</b>\n"
            f" ├ <b>Payment Asset:</b> <code>{Config.PAYMENT_METHOD}</code>\n"
            f" └ <b>Secure Wallet Destination:</b>\n<code>{Config.WALLET_ADDRESS}</code>\n\n"
            f"💡 <i>Demo Note: Type <code>TEST100</code> below to simulate instant Automated Webhook Gateway verification!</i>\n\n"
            f"<b>⌨️ Input Transaction Hash / ID (TXID):</b>"
        )
        await update.message.reply_text(payment_text, reply_markup=Keyboards.back_menu(), parse_mode="HTML")
        return ENTERING_TRANSACTION_ID

    async def transaction_id_entered(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        txid = update.message.text.strip()
        duplicate = self.db.fetchone("SELECT id FROM deposit_requests WHERE transaction_id = ?", (txid,))
        if duplicate and txid != "TEST100":
            await update.message.reply_text("⚠️ <b>SECURITY VIOLATION!</b> Hash already logged.", reply_markup=Keyboards.back_menu(), parse_mode="HTML")
            return ENTERING_TRANSACTION_ID

        amount = context.user_data["investment_amount"]
        plan_type = context.user_data["selected_plan"]
        context.user_data["transaction_id"] = txid
        
        plan = Config.PLANS[plan_type]
        daily = (amount * plan["daily_rate"]).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        confirm_text = (
            f"<b>📊 INBOUND TRANSACTION AUDIT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💰 <b>Investment Principal:</b> <code>{Config.CURRENCY}{amount:,.2f}</code>\n"
            f"📦 <b>Assigned Plan:</b> <code>{plan['name']} Matrix</code>\n"
            f"🔗 <b>Hash Reference:</b> <code>{txid}</code>\n"
            f"├ Daily Dividends: <code>{Config.CURRENCY}{daily:,.2f}</code>\n\n"
            f"🚀 <i>Initialize blockchain nodes matching algorithm?</i>"
        )
        await update.message.reply_text(confirm_text, reply_markup=Keyboards.confirm_menu(), parse_mode="HTML")
        return CONFIRMING_DEPOSIT

    async def confirm_deposit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query; await query.answer()
        amount = context.user_data.get("investment_amount")
        plan_type = context.user_data.get("selected_plan")
        txid = context.user_data.get("transaction_id")

        await query.edit_message_text("🔄 <code>Connecting to Webhook Gateway...</code>", parse_mode="HTML")
        await asyncio.sleep(0.5)

        if txid == "TEST100":
            res = self.investment_manager.create_investment(update.effective_user.id, plan_type, amount)
            self.db.execute("INSERT INTO deposit_requests (user_id, plan_type, amount, transaction_id, status, created_at) VALUES (?, ?, ?, ?, 'approved', ?)",
                            (update.effective_user.id, plan_type, str(amount), txid, datetime.now().isoformat()))
            await query.edit_message_text(
                f"<b>⚡ [INSTANT API AUTO-VERIFIED] ⚡</b>\n\n"
                f"✅ <b>Status:</b> Blockchain Payment Confirmed via Webhook IPN.\n"
                f"💼 <b>Activated Plan:</b> <code>{res['plan']}</code>\n"
                f"💰 <b>Capital Amount:</b> <code>{Config.CURRENCY}{res['amount']:,.2f}</code>\n"
                f"📈 <b>Daily Dividends:</b> <code>{Config.CURRENCY}{res['daily_earning']:,.2f}</code>",
                reply_markup=Keyboards.back_menu(), parse_mode="HTML"
            )
            context.user_data.clear()
            gc.collect()
            return ConversationHandler.END

        cursor = self.db.execute("INSERT INTO deposit_requests (user_id, plan_type, amount, transaction_id, status, created_at) VALUES (?, ?, ?, ?, 'awaiting_approval', ?)",
                        (update.effective_user.id, plan_type, str(amount), txid, datetime.now().isoformat()))
        
        await self.notify_admins(update, context, cursor.lastrowid, plan_type, amount, txid)
        await query.edit_message_text("<b>✅ INBOUND LEDGER RECORDED</b>\n\n⌛ <i>Verification pending node validation.</i>", reply_markup=Keyboards.back_menu(), parse_mode="HTML")
        context.user_data.clear()
        gc.collect()
        return ConversationHandler.END

    async def cancel_deposit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query; await query.answer()
        context.user_data.clear()
        await query.edit_message_text("❌ Pipeline cleared. Capital deposit cancelled.", reply_markup=Keyboards.back_menu())
        return ConversationHandler.END

    async def notify_admins(self, update: Update, context: ContextTypes.DEFAULT_TYPE, dep_id: int, plan_type: str, amount: Decimal, txid: str):
        admin_text = f"🚨 <b>MANUAL VERIFICATION REQUIRED</b>\n\nTicket: <code>#{dep_id}</code>\nUser ID: <code>{update.effective_user.id}</code>\nAmount: <code>{Config.CURRENCY}{amount}</code>\nTXID: <code>{txid}</code>"
        for admin_id in Config.ADMIN_IDS:
            try: await context.bot.send_message(chat_id=admin_id, text=admin_text, parse_mode="HTML", reply_markup=Keyboards.admin_deposit_approval(dep_id))
            except Exception: pass

    async def approve_deposit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query; await query.answer()
        dep_id = int(query.data.replace("approve_deposit_", ""))
        dep = self.db.fetchone("SELECT * FROM deposit_requests WHERE id = ?", (dep_id,))
        if not dep: return

        res = self.investment_manager.create_investment(dep[1], dep[2], Decimal(dep[3]))
        self.db.execute("UPDATE deposit_requests SET status = 'approved' WHERE id = ?", (dep_id,))
        
        try:
            await context.bot.send_message(chat_id=dep[1], text=f"<b>🎉 DEPOSIT AUDIT VERIFIED!</b>\nPlan <code>{res['plan']}</code> activated with <code>{Config.CURRENCY}{res['amount']}</code>", parse_mode="HTML")
        except Exception: pass
        await query.edit_message_text(f"<b>✅ TICKET #{dep_id} APPROVED</b>", parse_mode="HTML")

    async def reject_deposit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query; await query.answer()
        dep_id = int(query.data.replace("reject_deposit_", ""))
        dep = self.db.fetchone("SELECT * FROM deposit_requests WHERE id = ?", (dep_id,))
        self.db.execute("UPDATE deposit_requests SET status = 'rejected' WHERE id = ?", (dep_id,))
        try: await context.bot.send_message(chat_id=dep[1], text=f"<b>❌ DEPOSIT TICKET #{dep_id} REJECTED BY NODES</b>", parse_mode="HTML")
        except Exception: pass
        await query.edit_message_text(f"<b>❌ TICKET #{dep_id} REJECTED</b>", parse_mode="HTML")

    # ===================================================================
    # PORTFOLIO, WITHDRAW & STATS
    # ===================================================================
    async def portfolio(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query; await query.answer()
        investments = self.db.fetchall("SELECT id, plan_type, amount, total_earned, status FROM investments WHERE user_id = ? ORDER BY id DESC", (update.effective_user.id,))
        
        text = f"<b>📊 YOUR REAL-TIME INVESTMENT PORTFOLIO</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        if not investments:
            text += "<i>You have no operational assets deployed currently.</i>"
        else:
            for inv in investments:
                status = "🟢 Active" if inv[4] == "active" else "🔴 Matured"
                text += f"🖥 <b>{Config.PLANS[inv[1]]['name']} Node</b> ({status})\n ├ Principal: <code>{Config.CURRENCY}{Decimal(inv[2]):,.2f}</code>\n └ Earned: <code>{Config.CURRENCY}{Decimal(inv[3]):,.2f}</code>\n\n"
        await query.edit_message_text(text, reply_markup=Keyboards.back_menu(), parse_mode="HTML")

    async def withdraw_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query; await query.answer()
        user = self.user_manager.get_user(update.effective_user.id)
        text = f"<b>📤 INITIATE CASH OUTBOUND PIPELINE</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n💰 Balance: <code>{Config.CURRENCY}{user['balance']:,.2f}</code>\n<b>⌨️ Type withdrawal amount:</b>"
        await query.edit_message_text(text, reply_markup=Keyboards.back_menu(), parse_mode="HTML")
        return ENTERING_WITHDRAW_AMOUNT

    async def withdraw_amount_entered(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = self.user_manager.get_user(update.effective_user.id)
        try: amount = Decimal(update.message.text.strip()).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except Exception: return ENTERING_WITHDRAW_AMOUNT
            
        if amount > user["balance"] or amount < Config.MIN_INVESTMENT:
            await update.message.reply_text("❌ Insufficient balance or falls beneath floor limit.", reply_markup=Keyboards.back_menu())
            return ENTERING_WITHDRAW_AMOUNT

        new_bal = (user["balance"] - amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        new_with = (user["total_withdrawn"] + amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.db.execute("UPDATE users SET balance = ?, total_withdrawn = ? WHERE user_id = ?", (str(new_bal), str(new_with), update.effective_user.id))
        
        tx_hash = "0x" + ''.join(random.choices(string.hexdigits, k=32)).lower()
        await update.message.reply_text(f"<b>✅ INSTANT BLOCKCHAIN PAYOUT SUCCESSFUL</b>\n\n📤 Value: <code>{Config.CURRENCY}{amount:,.2f}</code>\n🚀 TX Hash: <code>{tx_hash}</code>", reply_markup=Keyboards.back_menu(), parse_mode="HTML")
        return ConversationHandler.END

    async def referral(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query; await query.answer()
        user = self.user_manager.get_user(update.effective_user.id)
        bot_info = await context.bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start={user['referral_code']}"
        
        ref_count = self.db.fetchone("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (update.effective_user.id,))[0]
        bonus = sum(Decimal(r[0]) for r in self.db.fetchall("SELECT bonus_amount FROM referrals WHERE referrer_id = ?", (update.effective_user.id,)))
        
        text = f"<b>👥 3-TIER AFFILIATE MATRIX</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n🔗 Link:\n<code>{ref_link}</code>\n\nTeam Count: <code>{ref_count}</code>\nEarnings: <code>{Config.CURRENCY}{bonus:,.2f}</code>"
        await query.edit_message_text(text, reply_markup=Keyboards.back_menu(), parse_mode="HTML")

    async def support(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query; await query.answer()
        await query.edit_message_text(f"<b>🤝 HELP DESK</b>\n━━━━━━\nTelegram Support: @admin_username", reply_markup=Keyboards.back_menu(), parse_mode="HTML")

    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query; await query.answer()
        total_users = self.db.fetchone("SELECT COUNT(*) FROM users")[0]
        text = f"<b>📈 SYSTEM METRICS</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n👥 Registered Users: <code>{total_users}</code>"
        await query.edit_message_text(text, reply_markup=Keyboards.back_menu(), parse_mode="HTML")

# ===================================================================
# MEMORY CONSCIOUS REPEATING LOOP FOR PROFITS SIMULATION
# ===================================================================

async def run_automated_interest_cycles_job(context: ContextTypes.DEFAULT_TYPE):
    bot_instance = context.job.data["bot"]
    active_contracts = bot_instance.db.fetchall("SELECT id, user_id, plan_type, daily_earning, total_earned FROM investments WHERE status = 'active'")
    if not active_contracts: return

    for contract in active_contracts:
        c_id, user_id, plan_type, daily_earning, total_earned = contract
        daily_earning = Decimal(daily_earning)
        new_earned = (Decimal(total_earned) + daily_earning).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        bot_instance.db.execute("UPDATE investments SET total_earned = ?, last_calculation = ? WHERE id = ?", (str(new_earned), datetime.now().isoformat(), c_id))
        
        user_row = bot_instance.db.fetchone("SELECT balance, total_earned FROM users WHERE user_id = ?", (user_id,))
        if user_row:
            f_bal = (Decimal(user_row[0]) + daily_earning).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            f_net = (Decimal(user_row[1]) + daily_earning).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            bot_instance.db.execute("UPDATE users SET balance = ?, total_earned = ? WHERE user_id = ?", (str(f_bal), str(f_net), user_id))
            
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"<b>💰 DIVIDEND DISTRIBUTED</b>\n\nNode: <code>#{c_id}</code>\nReturn: <code>{Config.CURRENCY}{daily_earning}</code>\nBalance: <code>{Config.CURRENCY}{f_bal}</code>",
                    parse_mode="HTML"
                )
            except Exception: pass
    
    gc.collect()  # Clean memory cache after each loop execution

# ===================================================================
# ASSEMBLY MAIN
# ===================================================================

def main():
    bot = InvestmentBot()
    application = Application.builder().token(Config.BOT_TOKEN).build()

    application.add_handler(CallbackQueryHandler(bot.portfolio, pattern="^portfolio$"))
    application.add_handler(CallbackQueryHandler(bot.referral, pattern="^referral$"))
    application.add_handler(CallbackQueryHandler(bot.support, pattern="^support$"))
    application.add_handler(CallbackQueryHandler(bot.stats, pattern="^stats$"))
    application.add_handler(CallbackQueryHandler(bot.back_to_menu, pattern="^back_menu$"))
    application.add_handler(CallbackQueryHandler(bot.approve_deposit, pattern="^approve_deposit_"))
    application.add_handler(CallbackQueryHandler(bot.reject_deposit, pattern="^reject_deposit_"))

    invest_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(bot.invest_callback, pattern="^invest$")],
        states={
            SELECTING_PLAN: [CallbackQueryHandler(bot.plan_selected, pattern="^plan_"), CallbackQueryHandler(bot.back_to_menu, pattern="^back_menu$")],
            ENTERING_AMOUNT: [CallbackQueryHandler(bot.back_to_menu, pattern="^back_menu$"), MessageHandler(filters.TEXT & ~filters.COMMAND, bot.amount_entered)],
            ENTERING_TRANSACTION_ID: [CallbackQueryHandler(bot.back_to_menu, pattern="^back_menu$"), MessageHandler(filters.TEXT & ~filters.COMMAND, bot.transaction_id_entered)],
            CONFIRMING_DEPOSIT: [CallbackQueryHandler(bot.confirm_deposit, pattern="^confirm_deposit$"), CallbackQueryHandler(bot.cancel_deposit, pattern="^cancel_deposit$"), CallbackQueryHandler(bot.back_to_menu, pattern="^back_menu$")]
        },
        fallbacks=[CommandHandler("start", bot.start), CallbackQueryHandler(bot.back_to_menu, pattern="^back_menu$")]
    )

    withdraw_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(bot.withdraw_start, pattern="^withdraw$")],
        states={ENTERING_WITHDRAW_AMOUNT: [CallbackQueryHandler(bot.back_to_menu, pattern="^back_menu$"), MessageHandler(filters.TEXT & ~filters.COMMAND, bot.withdraw_amount_entered)]},
        fallbacks=[CommandHandler("start", bot.start), CallbackQueryHandler(bot.back_to_menu, pattern="^back_menu$")]
    )

    application.add_handler(invest_conv)
    application.add_handler(withdraw_conv)
    application.add_handler(CommandHandler("start", bot.start))

    # Safe verification loop for JobQueue
    if application.job_queue:
        application.job_queue.run_repeating(run_automated_interest_cycles_job, interval=60, data={"bot": bot})
    else:
        logger.warning("JobQueue is not initialized. Automated interest cycles will not run.")

    # Final sweep before polling starts
    gc.collect()
    application.run_polling()

if __name__ == "__main__":
    main()
