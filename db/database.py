import os
from tortoise import Tortoise, fields
from tortoise.models import Model

class User(Model):
    id = fields.BigIntField(pk=True)
    username = fields.CharField(max_length=255, null=True)
    first_name = fields.CharField(max_length=255, null=True)
    joined_at = fields.DatetimeField(auto_now_add=True)
    
    is_premium = fields.BooleanField(default=False)
    premium_expiry_date = fields.DateField(null=True) 
    
    done_today = fields.IntField(default=0)
    last_use_date = fields.DateField(null=True)

    class Meta:
        table = "users"

async def init_db():
    db_url = os.getenv('DB_URL', 'sqlite://db.sqlite3')
    await Tortoise.init(
        db_url=db_url,
        modules={'models': ['db.database']}
    )

    await Tortoise.generate_schemas()