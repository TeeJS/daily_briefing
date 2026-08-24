"""
Diagnostic: find the correct MAPI property name for Focused vs Other inbox items.
Run from a STANDARD (non-elevated) PowerShell:
    .venv\Scripts\python.exe scripts\diag_outlook_focused.py
"""
import pythoncom
import win32com.client

CANDIDATES = [
    "http://schemas.microsoft.com/mapi/proptag/0x12130003",  # Focused Inbox: 0=Focused, 1=Other
    "http://schemas.microsoft.com/exchange/IsFocused",
    "http://schemas.microsoft.com/exchange/IsClutter",
    "http://schemas.microsoft.com/mapi/proptag/0x11630003",
    "http://schemas.microsoft.com/mapi/proptag/0x10F40003",
]

pythoncom.CoInitialize()
try:
    outlook = win32com.client.Dispatch("Outlook.Application")
    ns = outlook.GetNamespace("MAPI")
    inbox = ns.GetDefaultFolder(6)

    items = inbox.Items
    items.Sort("[ReceivedTime]", True)

    print(f"Inbox item count: {items.Count}")
    print("Checking first 10 items for candidate Focused/Other properties...\n")

    for i in range(min(10, items.Count)):
        msg = items.Item(i + 1)
        if not hasattr(msg, "Subject"):
            continue
        print(f"[{i+1}] {msg.Subject[:60]}")
        print(f"     Sender: {getattr(msg, 'SenderName', '?')}")
        for prop in CANDIDATES:
            label = prop.split("/")[-1]
            try:
                val = msg.PropertyAccessor.GetProperty(prop)
                print(f"     {label}: {val}")
            except Exception as e:
                print(f"     {label}: N/A ({type(e).__name__})")
        print()
finally:
    pythoncom.CoUninitialize()
