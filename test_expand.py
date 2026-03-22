import os
import re

def expand_vars(text):
    if not isinstance(text, str): return text
    
    # Placeholder for escaped $$
    placeholder = "___SCICD_ESCAPED_DOLLAR___"
    text = text.replace("$$", placeholder)
    
    # Expand real variables
    text = os.path.expandvars(text)
    
    # Restore escaped $
    text = text.replace(placeholder, "$")
    return text

os.environ["USER"] = "alice"
print(f"Normal: {expand_vars('$USER')}")
print(f"Escaped: {expand_vars('$$USER')}")
print(f"Mixed: {expand_vars('Hello $$USER, I am $USER')}")
