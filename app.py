import sqlite3
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import logging
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import requests
import qrcode
from io import BytesIO
from base64 import b64encode, b64decode
from PIL import Image, ImageTk
from datetime import datetime
import socket

app = Flask(__name__)
CORS(app)

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[
    logging.FileHandler("supermarket.log"),
    logging.StreamHandler()
])
logger = logging.getLogger(__name__)

# Database setup
def init_db():
    conn = sqlite3.connect("supermarket.db", check_same_thread=False)
    c = conn.cursor()
    # Products table with additional fields
    c.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            barcode TEXT UNIQUE NOT NULL,
            product_type TEXT,           -- From barcode (e.g., "General", "Food")
            manufacturer_code TEXT,      -- From barcode
            product_code TEXT,          -- From barcode
            name TEXT NOT NULL,         -- Auto-generated or user-edited
            buy_price REAL NOT NULL DEFAULT 0.0,
            sell_price REAL NOT NULL DEFAULT 0.0,
            discount REAL NOT NULL DEFAULT 0.0,  -- New discount field
            stock INTEGER NOT NULL DEFAULT 0
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            barcode TEXT NOT NULL,
            name TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            total REAL NOT NULL,
            timestamp TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()
    logger.info("Database initialized")

# Decode barcode (simple logic, extendable with GS1 lookup)
def decode_barcode(barcode):
    barcode = str(barcode).strip()
    if len(barcode) == 13:  # EAN-13
        prefix = barcode[:3]
        manufacturer_code = barcode[3:7]
        product_code = barcode[7:12]
        product_type = "General" if prefix.startswith("50") else "Unknown"  # Example: UK prefix
        name = f"Product {product_code}"  # Placeholder name
    elif len(barcode) == 12:  # UPC-A
        prefix = barcode[0]
        manufacturer_code = barcode[1:6]
        product_code = barcode[6:11]
        product_type = "General" if prefix == "0" else "Unknown"
        name = f"Item {product_code}"
    else:
        manufacturer_code = barcode[:len(barcode)//2]
        product_code = barcode[len(barcode)//2:]
        product_type = "Unknown"
        name = f"Unknown {barcode}"
    return {
        "product_type": product_type,
        "manufacturer_code": manufacturer_code,
        "product_code": product_code,
        "name": name,
        "buy_price": 1.0,  # Default buy price (logic can be refined)
        "stock": 10        # Default stock
    }

@app.route('/api/server-ip', methods=['GET'])
def get_server_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        s.connect(('8.8.8.8', 80))
        ip_address = s.getsockname()[0]
        s.close()
        return jsonify({"ip": ip_address}), 200
    except Exception as e:
        logger.error(f"Error detecting IP: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/products', methods=['POST'])
def add_product():
    try:
        data = request.get_json()
        if not data or 'barcode' not in data:
            return jsonify({"error": "Barcode required"}), 400
        barcode = data['barcode']
        conn = sqlite3.connect("supermarket.db")
        c = conn.cursor()
        c.execute("SELECT * FROM products WHERE barcode = ?", (barcode,))
        if c.fetchone():
            conn.close()
            return jsonify({"message": "Product exists"}), 409

        # Decode barcode for initial data
        decoded = decode_barcode(barcode)
        name = data.get('name', decoded['name'])
        buy_price = float(data.get('buy_price', decoded['buy_price']))
        sell_price = float(data.get('sell_price', 5.0))  # Default to 0, user will set
        discount = float(data.get('discount', 0.0))      # Default to 0
        stock = int(data.get('stock', decoded['stock']))
        
        c.execute("""
            INSERT INTO products (barcode, product_type, manufacturer_code, product_code, name, buy_price, sell_price, discount, stock)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (barcode, decoded['product_type'], decoded['manufacturer_code'], decoded['product_code'], name, buy_price, sell_price, discount, stock))
        conn.commit()
        conn.close()
        logger.info(f"Added product: {barcode}")
        return jsonify({"message": "Product added", "barcode": barcode}), 201
    except Exception as e:
        logger.error(f"Error adding product: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/products', methods=['GET'])
def get_products():
    try:
        conn = sqlite3.connect("supermarket.db")
        c = conn.cursor()
        c.execute("SELECT * FROM products")
        rows = c.fetchall()
        conn.close()
        keys = ["id", "barcode", "product_type", "manufacturer_code", "product_code", "name", "buy_price", "sell_price", "discount", "stock"]
        return jsonify([dict(zip(keys, row)) for row in rows]), 200
    except Exception as e:
        logger.error(f"Error fetching products: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/products/<int:id>', methods=['PUT'])
def update_product(id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
        conn = sqlite3.connect("supermarket.db")
        c = conn.cursor()
        c.execute("""
            UPDATE products SET name = ?, buy_price = ?, sell_price = ?, discount = ?, stock = ?
            WHERE id = ?
        """, (data['name'], float(data['buy_price']), float(data['sell_price']), float(data.get('discount', 0.0)), int(data['stock']), id))
        if c.rowcount == 0:
            conn.close()
            return jsonify({"error": "Product not found"}), 404
        conn.commit()
        conn.close()
        logger.info(f"Updated product ID: {id}")
        return jsonify({"message": "Product updated"}), 200
    except Exception as e:
        logger.error(f"Error updating product: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/products/<int:id>', methods=['DELETE'])
def delete_product(id):
    try:
        conn = sqlite3.connect("supermarket.db")
        c = conn.cursor()
        c.execute("DELETE FROM products WHERE id = ?", (id,))
        if c.rowcount == 0:
            conn.close()
            return jsonify({"error": "Product not found"}), 404
        conn.commit()
        conn.close()
        logger.info(f"Deleted product ID: {id}")
        return jsonify({"message": "Product deleted"}), 200
    except Exception as e:
        logger.error(f"Error deleting product: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/products/barcode/<barcode>', methods=['GET'])
def get_product_by_barcode(barcode):
    try:
        conn = sqlite3.connect("supermarket.db")
        c = conn.cursor()
        c.execute("SELECT * FROM products WHERE barcode = ?", (barcode,))
        row = c.fetchone()
        conn.close()
        if row:
            keys = ["id", "barcode", "product_type", "manufacturer_code", "product_code", "name", "buy_price", "sell_price", "discount", "stock"]
            return jsonify(dict(zip(keys, row))), 200
        return jsonify({"error": "Product not found"}), 404
    except Exception as e:
        logger.error(f"Error fetching product by barcode: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/transaction', methods=['POST'])
def record_transaction():
    try:
        data = request.get_json()
        if not data or 'items' not in data:
            return jsonify({"error": "Items required"}), 400
        conn = sqlite3.connect("supermarket.db")
        c = conn.cursor()
        total = 0
        for item in data['items']:
            barcode = item['barcode']
            quantity = int(item['quantity'])
            c.execute("SELECT name, sell_price, discount, stock FROM products WHERE barcode = ?", (barcode,))
            row = c.fetchone()
            if not row or row[3] < quantity:
                conn.close()
                return jsonify({"error": f"Insufficient stock or invalid product: {barcode}"}), 400
            name, sell_price, discount, stock = row
            discounted_price = sell_price * (1 - discount / 100)  # Apply discount as percentage
            total += discounted_price * quantity
            c.execute("UPDATE products SET stock = stock - ? WHERE barcode = ?", (quantity, barcode))
            c.execute("INSERT INTO transactions (barcode, name, quantity, total, timestamp) VALUES (?, ?, ?, ?, datetime('now'))",
                      (barcode, name, quantity, discounted_price * quantity))
        conn.commit()
        conn.close()
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(f"Payment: ${total:.2f}|TransactionID:{c.lastrowid}")
        qr.make(fit=True)
        img = qr.make_image(fill='black', back_color='white')
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        qr_base64 = b64encode(buffer.getvalue()).decode('utf-8')
        logger.info(f"Transaction recorded, total: ${total:.2f}")
        return jsonify({"message": "Transaction recorded", "total": total, "qr_code": qr_base64}), 201
    except Exception as e:
        logger.error(f"Error recording transaction: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/')
def serve_scanner():
    return send_from_directory('static', 'scanner.html')

class SupermarketPOS:
    def __init__(self, root):
        self.root = root
        self.root.title("Supermarket Scanner")
        self.root.geometry("1200x800")
        self.root.configure(bg="#f0f4f8")

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background="#ffffff", tabfocuscolor="#007bff")
        style.configure("TNotebook.Tab", background="#e9ecef", padding=[10, 5], font=("Arial", 12, "bold"))
        style.map("TNotebook.Tab", background=[("selected", "#007bff")], foreground=[("selected", "white")])
        style.configure("TButton", font=("Arial", 11), padding=5)
        style.map("TButton", background=[("active", "#0056b3")], foreground=[("active", "white")])
        style.configure("Treeview", font=("Arial", 10), rowheight=25)
        style.configure("Treeview.Heading", font=("Arial", 11, "bold"), background="#007bff", foreground="white")

        self.main_frame = tk.Frame(self.root, bg="#f0f4f8")
        self.main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        header = tk.Label(self.main_frame, text="Supermarket Scanner", font=("Arial", 24, "bold"), fg="#007bff", bg="#f0f4f8")
        header.pack(pady=10)

        self.notebook = ttk.Notebook(self.main_frame)
        self.notebook.pack(fill="both", expand=True)

        self.inventory_tab = tk.Frame(self.notebook, bg="#ffffff")
        self.checkout_tab = tk.Frame(self.notebook, bg="#ffffff")
        self.history_tab = tk.Frame(self.notebook, bg="#ffffff")

        self.notebook.add(self.inventory_tab, text="Inventory")
        self.notebook.add(self.checkout_tab, text="Checkout")
        self.notebook.add(self.history_tab, text="Transaction History")

        self.status_var = tk.StringVar(value="Ready")
        self.status_bar = tk.Label(self.main_frame, textvariable=self.status_var, font=("Arial", 12), bg="#ffc107", fg="#212529",
                                   relief="sunken", anchor="w", padx=10)
        self.status_bar.pack(fill="x", pady=5)

        self.create_inventory_tab()
        self.create_checkout_tab()
        self.create_history_tab()

        self.cart = []
        self.processed_barcodes = set()
        self.is_polling = True
        self.start_polling()

    def create_inventory_tab(self):
        frame = tk.Frame(self.inventory_tab, bg="#ffffff")
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.inv_tree = ttk.Treeview(frame, columns=("ID", "Barcode", "Name", "Buy Price", "Sell Price", "Discount", "Stock"), show="headings")
        for col in ("ID", "Barcode", "Name", "Buy Price", "Sell Price", "Discount", "Stock"):
            self.inv_tree.heading(col, text=col)
            self.inv_tree.column(col, width=100 if col == "ID" else 150)
        self.inv_tree.pack(fill="both", expand=True)

        button_frame = tk.Frame(frame, bg="#ffffff")
        button_frame.pack(pady=10)
        tk.Button(button_frame, text="Update", command=self.update_product, bg="#28a745", fg="white", font=("Arial", 11)).pack(side="left", padx=5)
        tk.Button(button_frame, text="Delete", command=self.delete_product, bg="#dc3545", fg="white", font=("Arial", 11)).pack(side="left", padx=5)
        tk.Button(button_frame, text="Refresh", command=self.refresh_products, bg="#007bff", fg="white", font=("Arial", 11)).pack(side="left", padx=5)

        self.refresh_products()

    def create_checkout_tab(self):
        frame = tk.Frame(self.checkout_tab, bg="#ffffff")
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        tk.Label(frame, text="Checkout", font=("Arial", 20, "bold"), fg="#007bff", bg="#ffffff").pack(pady=5)

        self.cart_tree = ttk.Treeview(frame, columns=("Barcode", "Name", "Price", "Discount", "Quantity", "Subtotal"), show="headings")
        for col in ("Barcode", "Name", "Price", "Discount", "Quantity", "Subtotal"):
            self.cart_tree.heading(col, text=col)
            self.cart_tree.column(col, width=150)
        self.cart_tree.pack(fill="both", expand=True)

        total_frame = tk.Frame(frame, bg="#ffffff")
        total_frame.pack(fill="x", pady=10)
        self.total_var = tk.StringVar(value="Total: $0.00")
        tk.Label(total_frame, textvariable=self.total_var, font=("Arial", 16, "bold"), fg="#212529", bg="#ffffff").pack(side="left", padx=10)

        button_frame = tk.Frame(frame, bg="#ffffff")
        button_frame.pack(pady=10)
        tk.Button(button_frame, text="Remove Item", command=self.remove_cart_item, bg="#dc3545", fg="white", font=("Arial", 11)).pack(side="left", padx=5)
        tk.Button(button_frame, text="Clear Cart", command=self.clear_cart, bg="#ffc107", fg="#212529", font=("Arial", 11)).pack(side="left", padx=5)
        tk.Button(button_frame, text="Checkout", command=self.checkout, bg="#28a745", fg="white", font=("Arial", 11)).pack(side="left", padx=5)

    def create_history_tab(self):
        frame = tk.Frame(self.history_tab, bg="#ffffff")
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.hist_tree = ttk.Treeview(frame, columns=("ID", "Barcode", "Name", "Quantity", "Total", "Timestamp"), show="headings")
        for col in ("ID", "Barcode", "Name", "Quantity", "Total", "Timestamp"):
            self.hist_tree.heading(col, text=col)
            self.hist_tree.column(col, width=100 if col == "ID" else 150)
        self.hist_tree.pack(fill="both", expand=True)

        tk.Button(frame, text="Refresh", command=self.refresh_history, bg="#007bff", fg="white", font=("Arial", 11)).pack(pady=10)

        self.refresh_history()

    def refresh_products(self):
        try:
            for item in self.inv_tree.get_children():
                self.inv_tree.delete(item)
            response = requests.get("https://127.0.0.1:5000/api/products", verify=False)
            if response.status_code == 200:
                for product in response.json():
                    self.inv_tree.insert("", "end", values=(product["id"], product["barcode"], product["name"],
                                                            product["buy_price"], product["sell_price"], 
                                                            product["discount"], product["stock"]))
                    if product["stock"] < 5:
                        messagebox.showwarning("Low Stock", f"{product['name']} has only {product['stock']} items left!")
            self.status_var.set("Inventory refreshed")
            self.status_bar.config(bg="#28a745", fg="white")
        except Exception as e:
            logger.error(f"Error refreshing products: {str(e)}")
            self.status_var.set(f"Error: {str(e)}")
            self.status_bar.config(bg="#dc3545", fg="white")

    def refresh_history(self):
        try:
            for item in self.hist_tree.get_children():
                self.hist_tree.delete(item)
            conn = sqlite3.connect("supermarket.db")
            c = conn.cursor()
            c.execute("SELECT * FROM transactions ORDER BY timestamp DESC")
            for row in c.fetchall():
                self.hist_tree.insert("", "end", values=row)
            conn.close()
            self.status_var.set("History refreshed")
            self.status_bar.config(bg="#28a745", fg="white")
        except Exception as e:
            logger.error(f"Error refreshing history: {str(e)}")
            self.status_var.set(f"Error: {str(e)}")
            self.status_bar.config(bg="#dc3545", fg="white")

    def update_product(self):
        selected = self.inv_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Select a product to update.")
            return
        item = self.inv_tree.item(selected[0])["values"]
        id = item[0]

        popup = tk.Toplevel(self.root)
        popup.title("Update Product")
        popup.geometry("400x350")
        popup.configure(bg="#f0f4f8")

        fields = {"Name": item[2], "Buy Price": item[3], "Sell Price": item[4], "Discount (%)": item[5], "Stock": item[6]}
        entries = {}
        for i, (label, value) in enumerate(fields.items()):
            tk.Label(popup, text=f"{label}:", font=("Arial", 11), bg="#f0f4f8", fg="#212529").grid(row=i, column=0, padx=10, pady=5, sticky="e")
            entries[label] = tk.Entry(popup, font=("Arial", 11), width=25)
            entries[label].grid(row=i, column=1, padx=10, pady=5)
            entries[label].insert(0, value)

        def save():
            try:
                data = {
                    "name": entries["Name"].get(),
                    "buy_price": float(entries["Buy Price"].get()),
                    "sell_price": float(entries["Sell Price"].get()),
                    "discount": float(entries["Discount (%)"].get() or 0),
                    "stock": int(entries["Stock"].get())
                }
                response = requests.put(f"https://127.0.0.1:5000/api/products/{id}", json=data, verify=False)
                response.raise_for_status()
                messagebox.showinfo("Success", "Product updated!")
                self.refresh_products()
                popup.destroy()
                self.status_var.set("Product updated")
                self.status_bar.config(bg="#28a745", fg="white")
            except Exception as e:
                messagebox.showerror("Error", str(e))
                self.status_var.set(f"Error: {str(e)}")
                self.status_bar.config(bg="#dc3545", fg="white")

        tk.Button(popup, text="Save", command=save, bg="#007bff", fg="white", font=("Arial", 11)).grid(row=5, column=0, columnspan=2, pady=10)

    def delete_product(self):
        selected = self.inv_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Select a product to delete.")
            return
        item = self.inv_tree.item(selected[0])["values"]
        id = item[0]

        if messagebox.askyesno("Confirm", f"Delete '{item[1]}'?"):
            try:
                response = requests.delete(f"https://127.0.0.1:5000/api/products/{id}", verify=False)
                response.raise_for_status()
                messagebox.showinfo("Success", "Product deleted!")
                self.refresh_products()
                self.status_var.set("Product deleted")
                self.status_bar.config(bg="#28a745", fg="white")
            except Exception as e:
                messagebox.showerror("Error", str(e))
                self.status_var.set(f"Error: {str(e)}")
                self.status_bar.config(bg="#dc3545", fg="white")

    def start_polling(self):
        def poll():
            if not self.is_polling:
                self.root.after(1000, poll)
                return
            try:
                response = requests.get("https://127.0.0.1:5000/api/products", timeout=2, verify=False)
                if response.status_code == 200:
                    products = response.json()
                    if products:
                        latest_product = products[-1]
                        barcode = latest_product["barcode"]
                        if barcode not in self.processed_barcodes and barcode not in [item["barcode"] for item in self.cart]:
                            product_response = requests.get(f"https://127.0.0.1:5000/api/products/barcode/{barcode}", verify=False)
                            if product_response.status_code == 200:
                                product = product_response.json()
                                if product["sell_price"] == 0.0:  # New product needing price
                                    self.processed_barcodes.add(barcode)
                                    self.show_product_details_popup(barcode)
                                else:
                                    self.add_to_cart(product)
                                    self.status_var.set(f"Added {product['name']} to cart")
                                    self.status_bar.config(bg="#28a745", fg="white")
                                    self.processed_barcodes.add(barcode)
            except Exception as e:
                logger.error(f"Polling error: {str(e)}")
                self.status_var.set(f"Polling error: {str(e)}")
                self.status_bar.config(bg="#dc3545", fg="white")
            self.root.after(1000, poll)
        self.root.after(1000, poll)

    def show_product_details_popup(self, barcode):
        self.is_polling = False
        decoded = decode_barcode(barcode)
        popup = tk.Toplevel(self.root)
        popup.title("Add Product Details")
        popup.geometry("400x400")
        popup.configure(bg="#f0f4f8")

        tk.Label(popup, text=f"Barcode: {barcode}", font=("Arial", 14), bg="#f0f4f8", fg="#212529").grid(row=0, column=0, columnspan=2, pady=5)
        fields = {
            "Product Type": decoded["product_type"],
            "Manufacturer Code": decoded["manufacturer_code"],
            "Product Code": decoded["product_code"],
            "Name": decoded["name"],
            "Buy Price": decoded["buy_price"],
            "Sell Price": 0.0,  # User must set this
            "Discount (%)": 0,  # Optional discount
            "Stock": decoded["stock"]
        }
        entries = {}
        for i, (label, default) in enumerate(fields.items(), 1):
            tk.Label(popup, text=f"{label}:", font=("Arial", 11), bg="#f0f4f8", fg="#212529").grid(row=i, column=0, padx=10, pady=5, sticky="e")
            entries[label] = tk.Entry(popup, font=("Arial", 11), width=25)
            entries[label].grid(row=i, column=1, padx=10, pady=5)
            entries[label].insert(0, default)

        def save():
            try:
                sell_price = float(entries["Sell Price"].get())
                if sell_price <= 0:
                    raise ValueError("Sell price must be greater than 0")
                data = {
                    "barcode": barcode,
                    "product_type": entries["Product Type"].get(),
                    "manufacturer_code": entries["Manufacturer Code"].get(),
                    "product_code": entries["Product Code"].get(),
                    "name": entries["Name"].get(),
                    "buy_price": float(entries["Buy Price"].get()),
                    "sell_price": sell_price,
                    "discount": float(entries["Discount (%)"].get() or 0),
                    "stock": int(entries["Stock"].get())
                }
                response = requests.post("https://127.0.0.1:5000/api/products", json=data, verify=False)
                response.raise_for_status()
                messagebox.showinfo("Success", "Product saved!")
                self.refresh_products()
                self.add_to_cart(data)
                popup.destroy()
                self.is_polling = True
                self.status_var.set("Product added")
                self.status_bar.config(bg="#28a745", fg="white")
            except Exception as e:
                messagebox.showerror("Error", str(e))
                self.is_polling = True

        tk.Button(popup, text="Save", command=save, bg="#007bff", fg="white", font=("Arial", 11)).grid(row=9, column=0, columnspan=2, pady=10)
        popup.protocol("WM_DELETE_WINDOW", lambda: [popup.destroy(), setattr(self, 'is_polling', True)])

    def add_to_cart(self, product):
        for item in self.cart:
            if item["barcode"] == product["barcode"]:
                item["quantity"] += 1
                self.update_cart_display()
                return
        self.cart.append({
            "barcode": product["barcode"],
            "name": product["name"],
            "price": product["sell_price"],
            "discount": product["discount"],
            "quantity": 1
        })
        self.update_cart_display()

    def update_cart_display(self):
        for item in self.cart_tree.get_children():
            self.cart_tree.delete(item)
        total = 0
        for item in self.cart:
            discounted_price = item["price"] * (1 - item["discount"] / 100)
            subtotal = discounted_price * item["quantity"]
            total += subtotal
            self.cart_tree.insert("", "end", values=(item["barcode"], item["name"], item["price"], item["discount"], item["quantity"], f"{subtotal:.2f}"))
        self.total_var.set(f"Total: ${total:.2f}")

    def remove_cart_item(self, event=None):
        selected = self.cart_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Select an item to remove.")
            return
        item = self.cart_tree.item(selected[0])["values"]
        barcode = item[0]
        self.cart = [i for i in self.cart if i["barcode"] != barcode]
        self.update_cart_display()
        self.status_var.set(f"Removed {item[1]} from cart")
        self.status_bar.config(bg="#ffc107", fg="#212529")

    def clear_cart(self):
        self.cart = []
        self.update_cart_display()
        self.status_var.set("Cart cleared")
        self.status_bar.config(bg="#ffc107", fg="#212529")

    def checkout(self):
        if not self.cart:
            messagebox.showwarning("Warning", "Cart is empty!")
            return
        try:
            response = requests.post("https://127.0.0.1:5000/api/transaction", json={"items": self.cart}, verify=False)
            response.raise_for_status()
            data = response.json()
            self.show_payment_qr(data["qr_code"], data["total"])
            self.cart = []
            self.update_cart_display()
            self.refresh_products()
            self.refresh_history()
            self.status_var.set("Checkout completed")
            self.status_bar.config(bg="#28a745", fg="white")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            self.status_var.set(f"Checkout error: {str(e)}")
            self.status_bar.config(bg="#dc3545", fg="white")

    def show_payment_qr(self, qr_base64, total):
        popup = tk.Toplevel(self.root)
        popup.title("Payment QR Code")
        popup.geometry("300x400")
        popup.configure(bg="#f0f4f8")

        tk.Label(popup, text=f"Total: ${total:.2f}", font=("Arial", 16), bg="#f0f4f8", fg="#212529").pack(pady=10)
        img_data = BytesIO(b64decode(qr_base64))
        img = Image.open(img_data)
        photo = ImageTk.PhotoImage(img)
        tk.Label(popup, image=photo, bg="#f0f4f8").pack(pady=10)
        popup.image = photo
        tk.Label(popup, text="Scan with payment app", font=("Arial", 11), bg="#f0f4f8", fg="#212529").pack(pady=5)
        tk.Button(popup, text="Close", command=popup.destroy, bg="#007bff", fg="white", font=("Arial", 11)).pack(pady=10)

def run_flask():
    logger.info("Starting Flask server on 0.0.0.0:5000 with HTTPS")
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False, ssl_context=('cert.pem', 'key.pem'))

if __name__ == "__main__":
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()
    root = tk.Tk()
    app = SupermarketPOS(root)
    root.mainloop()