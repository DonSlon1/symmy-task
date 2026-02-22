from django.db import models


class ProductSyncState(models.Model):
    sku = models.CharField(max_length=100, primary_key=True)
    data_hash = models.CharField(max_length=64)
    last_synced_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.sku} ({self.last_synced_at})"
