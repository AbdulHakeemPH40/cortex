#!/usr/bin/env python3
"""Test file for AI agent - has intentional bugs to fix."""

import os
import sys

def calculate_total(items):
    """Calculate total price from items list."""
    total = 0
    for item in items:
        total += item['price'] * item['quantity']
    return total

def apply_discount(total, discount_percent):
    """Apply discount to total."""
    discount_amount = total * (discount_percent / 100)
    return total - discount_amount

def process_order(items, discount=0, tax_rate=0.08):
    """Process an order and return final price."""
    subtotal = calculate_total(items)
    
    if discount > 0:
        discounted_total = apply_discount(subtotal, discount)
    else:
        discounted_total = subtotal
    
    # BUG: Missing tax calculation
    tax_amount = discounted_total * tax_rate
    final_total = discounted_total + tax_amount
    
    return final_total

def main():
    """Test the order processing."""
    test_items = [
        {'name': 'Widget', 'price': 10.00, 'quantity': 2},
        {'name': 'Gadget', 'price': 25.00, 'quantity': 1}
    ]
    
    subtotal = calculate_total(test_items)
    print(f"Subtotal: ${subtotal:.2f}")
    
    discounted = apply_discount(subtotal, 10)
    print(f"After 10% discount: ${discounted:.2f}")
    
    total = process_order(test_items, discount=10)
    print(f"Total with tax (8%): ${total:.2f}")

if __name__ == "__main__":
    main()
