#!/usr/bin/env python3
"""Test file for AI agent - has intentional bugs to fix."""

import os
import sys

def calculate_total(items):
    """Calculate total price from items list."""
    if not items:
        return 0.0
    
    total = 0
    for item in items:
        if 'price' not in item:
            raise ValueError(f"Item missing 'price' field: {item}")
        if 'quantity' not in item:
            raise ValueError(f"Item missing 'quantity' field: {item}")
        
        price = float(item['price'])
        quantity = int(item['quantity'])
        
        if price < 0:
            raise ValueError(f"Price cannot be negative: {price}")
        if quantity < 0:
            raise ValueError(f"Quantity cannot be negative: {quantity}")
        
        total += price * quantity
    
    return float(total)

def apply_discount(total, discount_percent):
    """Apply discount to total."""
    if discount_percent < 0:
        raise ValueError("Discount percentage cannot be negative")
    if discount_percent > 100:
        raise ValueError("Discount percentage cannot exceed 100%")
    
    discount_amount = total * (discount_percent / 100)
    return total - discount_amount

def process_order(items, discount=0, tax_rate=0.08):
    """Process an order and return final price."""
    if tax_rate < 0:
        raise ValueError("Tax rate cannot be negative")
    
    subtotal = calculate_total(items)
    
    if discount > 0:
        discounted_total = apply_discount(subtotal, discount)
    else:
        discounted_total = subtotal
    
    # BUG: Missing tax calculation - FIXED: Tax should be calculated on subtotal before discount
    tax_amount = subtotal * tax_rate
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
