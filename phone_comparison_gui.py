import psycopg2
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from tkinter import messagebox, Toplevel, Checkbutton, IntVar
from tkinter.ttk import Treeview, Scrollbar

# Database connection parameters
DB_PARAMS = {
    "dbname": "ph",
    "user": "postgres",
    "password": "12345",  # Replace with your postgres password
    "host": "localhost",
    "port": "5432"
}

def connect_db():
    """Connect to the PostgreSQL database."""
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        return conn
    except psycopg2.Error as e:
        messagebox.showerror("Database Error", f"Error connecting to database: {e}")
        exit(1)

def list_phones(conn, tree):
    """List all phones in the Treeview."""
    # Clear existing items
    for item in tree.get_children():
        tree.delete(item)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT p.id, p.name, p.brand, p.category, p.created_at
            FROM products p
            WHERE p.category = 'Smartphone'
            ORDER BY p.name;
        """)
        phones = cur.fetchall()

    # Configure Treeview columns
    tree["columns"] = ("ID", "Name", "Brand", "Category", "Created At")
    tree.heading("ID", text="ID")
    tree.heading("Name", text="Name")
    tree.heading("Brand", text="Brand")
    tree.heading("Category", text="Category")
    tree.heading("Created At", text="Created At")
    tree.column("ID", width=50)
    tree.column("Name", width=150)
    tree.column("Brand", width=100)
    tree.column("Category", width=100)
    tree.column("Created At", width=150)

    # Insert data
    for phone in phones:
        tree.insert("", END, values=phone)

def get_phone_specs(conn, product_id):
    """Get specifications for a specific phone."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT p.name, p.brand, ps.screen_size, ps.resolution, ps.camera_mp,
                   ps.battery, ps.processor, ps.ram, ps.storage
            FROM products p
            JOIN product_specs ps ON p.id = ps.product_id
            WHERE p.id = %s;
        """, (product_id,))
        return cur.fetchone()

def compare_phones_dialog(conn, tree):
    """Open a dialog to select phones for comparison."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM products WHERE category = 'Smartphone' ORDER BY name")
        phones = cur.fetchall()

    if len(phones) < 2:
        messagebox.showwarning("Warning", "At least two phones are required for comparison.")
        return

    # Create dialog window
    dialog = Toplevel()
    dialog.title("Select Phones to Compare")
    dialog.geometry("300x400")
    dialog.resizable(False, False)

    ttk.Label(dialog, text="Select phones to compare (at least 2):").pack(pady=10)

    # Create checkboxes
    selections = []
    for phone in phones:
        var = IntVar()
        Checkbutton(dialog, text=f"{phone[1]} (ID: {phone[0]})", variable=var).pack(anchor="w", padx=10)
        selections.append((phone[0], var))

    def submit():
        selected_ids = [phone_id for phone_id, var in selections if var.get() == 1]
        if len(selected_ids) < 2:
            messagebox.showerror("Error", "Please select at least two phones.")
            return
        dialog.destroy()
        display_comparison(conn, tree, selected_ids)

    ttk.Button(dialog, text="Compare", bootstyle=SUCCESS, command=submit).pack(pady=20)
    dialog.transient(tree.winfo_toplevel())
    dialog.grab_set()

def display_comparison(conn, tree, product_ids):
    """Display comparison of selected phones in the Treeview."""
    # Clear existing items
    for item in tree.get_children():
        tree.delete(item)

    specs_data = []
    for pid in product_ids:
        specs = get_phone_specs(conn, pid)
        if not specs:
            messagebox.showerror("Error", f"Phone with ID {pid} not found.")
            return
        specs_data.append(specs)

    # Configure Treeview columns
    tree["columns"] = ("Field", *[f"Phone {i+1}" for i in range(len(specs_data))])
    tree.heading("Field", text="Field")
    for i in range(len(specs_data)):
        tree.heading(f"Phone {i+1}", text=specs_data[i][0])  # Use phone name
        tree.column(f"Phone {i+1}", width=150)
    tree.column("Field", width=150)

    # Prepare comparison data
    fields = ["Name", "Brand", "Screen Size (in)", "Resolution", "Camera (MP)",
              "Battery (mAh)", "Processor", "RAM (GB)", "Storage (GB)"]
    for i, field in enumerate(fields):
        row = [field] + [str(spec[i]) for spec in specs_data]
        tree.insert("", END, values=row)

def view_prices_dialog(conn, tree):
    """Open a dialog to enter phone ID for viewing prices."""
    dialog = Toplevel()
    dialog.title("View Prices")
    dialog.geometry("300x200")
    dialog.resizable(False, False)

    ttk.Label(dialog, text="Enter Phone ID:").pack(pady=10)
    entry = ttk.Entry(dialog)
    entry.pack(pady=10)

    def submit():
        try:
            product_id = int(entry.get())
            dialog.destroy()
            display_prices(conn, tree, product_id)
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid ID.")

    ttk.Button(dialog, text="View Prices", bootstyle=SUCCESS, command=submit).pack(pady=20)
    dialog.transient(tree.winfo_toplevel())
    dialog.grab_set()

def display_prices(conn, tree, product_id):
    """Display prices for a specific phone in the Treeview."""
    # Clear existing items
    for item in tree.get_children():
        tree.delete(item)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT p.name, s.name, pr.price, pr.last_updated
            FROM products p
            JOIN prices pr ON p.id = pr.product_id
            JOIN stores s ON pr.store_id = s.id
            WHERE p.id = %s
            ORDER BY pr.price;
        """, (product_id,))
        prices = cur.fetchall()

    if not prices:
        messagebox.showinfo("Info", "No price data available for this phone.")
        return

    # Configure Treeview columns
    tree["columns"] = ("Phone Name", "Store", "Price ($)", "Last Updated")
    tree.heading("Phone Name", text="Phone Name")
    tree.heading("Store", text="Store")
    tree.heading("Price ($)", text="Price ($)")
    tree.heading("Last Updated", text="Last Updated")
    tree.column("Phone Name", width=150)
    tree.column("Store", width=150)
    tree.column("Price ($)", width=100)
    tree.column("Last Updated", width=150)

    # Insert data
    for price in prices:
        tree.insert("", END, values=price)

def main():
    """Main application function."""
    conn = connect_db()

    # Create main window
    root = ttk.Window(themename="flatly")
    root.title("Phone Comparison App")
    root.geometry("800x600")
    root.resizable(True, True)

    # Create main frame
    frame = ttk.Frame(root, padding=10)
    frame.pack(fill=BOTH, expand=True)

    # Create buttons
    ttk.Button(frame, text="List Phones", bootstyle=PRIMARY,
               command=lambda: list_phones(conn, tree)).pack(pady=5, fill=X)
    ttk.Button(frame, text="Compare Phones", bootstyle=INFO,
               command=lambda: compare_phones_dialog(conn, tree)).pack(pady=5, fill=X)
    ttk.Button(frame, text="View Prices", bootstyle=SUCCESS,
               command=lambda: view_prices_dialog(conn, tree)).pack(pady=5, fill=X)

    # Create Treeview with scrollbar
    tree_frame = ttk.Frame(frame)
    tree_frame.pack(pady=10, fill=BOTH, expand=True)

    tree = Treeview(tree_frame, show="headings", height=20)
    tree.pack(side=LEFT, fill=BOTH, expand=True)

    scrollbar = Scrollbar(tree_frame, orient=VERTICAL, command=tree.yview)
    scrollbar.pack(side=RIGHT, fill=Y)
    tree.configure(yscrollcommand=scrollbar.set)

    # Run application
    root.protocol("WM_DELETE_WINDOW", lambda: [conn.close(), root.destroy()])
    root.mainloop()

if __name__ == "__main__":
    main()
