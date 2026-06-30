from django.db import models
from .department import Department


class InventoryCategory(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name_plural = "Inventory Categories"

    def __str__(self):
        return self.name


class InventoryItem(models.Model):
    category = models.ForeignKey(InventoryCategory, on_delete=models.CASCADE, related_name='items')
    name = models.CharField(max_length=150)
    quantity = models.IntegerField(default=0)
    unit = models.CharField(max_length=50, default='pieces', help_text="e.g. pieces, liters, boxes")
    threshold_level = models.IntegerField(default=5, help_text="Minimum stock level before trigger low-stock alert")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.quantity} {self.unit})"


class Supplier(models.Model):
    name = models.CharField(max_length=150)
    contact_person = models.CharField(max_length=100, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name


class InventoryTransaction(models.Model):
    TRANSACTION_TYPES = [
        ('Restock', 'Restock'),
        ('Issue', 'Issue'),
    ]

    item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES, default='Issue')
    quantity = models.IntegerField()
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='inventory_issues')
    transaction_date = models.DateTimeField(auto_now_add=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name='restocks')
    remarks = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.transaction_type} of {self.quantity} x {self.item.name}"
