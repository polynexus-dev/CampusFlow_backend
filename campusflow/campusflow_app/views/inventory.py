from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from ..models.inventory import InventoryCategory, InventoryItem, Supplier, InventoryTransaction
from ..serializers import (
    InventoryCategorySerializer, InventoryItemSerializer,
    SupplierSerializer, InventoryTransactionSerializer
)
from ..permissions import RequiresModule

INVENTORY_PERMS = [IsAuthenticated, RequiresModule("inventory")]


class InventoryCategoryViewSet(viewsets.ModelViewSet):
    queryset = InventoryCategory.objects.all().order_by('name')
    serializer_class = InventoryCategorySerializer
    permission_classes = INVENTORY_PERMS


class InventoryItemViewSet(viewsets.ModelViewSet):
    queryset = InventoryItem.objects.select_related('category').all().order_by('name')
    serializer_class = InventoryItemSerializer
    permission_classes = INVENTORY_PERMS


class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.all().order_by('name')
    serializer_class = SupplierSerializer
    permission_classes = INVENTORY_PERMS


class InventoryTransactionViewSet(viewsets.ModelViewSet):
    queryset = InventoryTransaction.objects.select_related('item__category', 'department', 'supplier').all().order_by('-transaction_date')
    serializer_class = InventoryTransactionSerializer
    permission_classes = INVENTORY_PERMS
