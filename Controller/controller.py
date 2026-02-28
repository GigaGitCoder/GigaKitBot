import sqlite3
from fastapi import FastAPI, HTTPException
import json


# ========================================
# Эндпоинты user:
#   POST   /PostCreatePet/{user_id}?name=            — создать питомца 
#   GET    /GetPetBy/{user_id}                 — получить все данные питомца
#   GET    /GetMoney/{user_id}                 — получить деньги
#   GET    /GetName/{user_id}                  — получить имя
#   GET    /GetSatiety/{user_id}               — получить сытость
#   GET    /GetEnergy/{user_id}                — получить энергию
#   GET    /GetMood/{user_id}                  — получить настроение
#   GET    /GetStates/{user_id}                — получить состояни
#   GET    /GetPetInventory/{user_id}          — получить инвентарь питомца
#   GET    /GetUserInventory/{user_id}          — получить инвентарь пользователя   

#   DELETE /DeletePetBy/{user_id}              — удалить питомцvа                           
#   PATCH  /SetMoney/{user_id}?amount=                 — установить деньги (абсолют)
#   PATCH  /SetName/{user_id}?name=                   — изменить имя (макс. 15 символов)
#   PATCH  /SetSatiety/{user_id}?value=               — установить сытость (0–100, абсолют)
#   PATCH  /SetEnergy/{user_id}?value=                — установить энергию (0–100, абсолют)
#   PATCH  /SetMood/{user_id}?value=                    — установить настроение (0–100, абсолют)
#   PATCH  /SetStates/{user_id}  body: {"ключ": "значение", ...}               1  — полностью заменить все состояния
#   PATCH  /AddPetItem/{user_id}?item=              — добавить предмет в инвентарь питомца
#   DELETE /RemovePetItem/{user_id}?item=            — удалить предмет из инвентаря питомца
#   PATCH  /AddUserItem/{user_id}?item=              — добавить предмет в инвентарь пользователя
#   DELETE /RemoveUserItem/{user_id}?item=            — удалить предмет из инвентаря пользователя

#   PATCH  /AllMoneyMinus/{user_id}?n=               — вычесть n от денег
#   PATCH  /AllSatietyMinus/{user_id}?n=             — вычесть n от сытости (clamp 0–100)
#   PATCH  /AllEnergyMinus/{user_id}?n=              — вычесть n от энергии (clamp 0–100)
#   PATCH  /AllMoodMinus/{user_id}?n=                — вычесть n от настроения (clamp 0–100)

#   GET    /GetAllUserIDByMoneyUnderN?n=             — user_id у кого деньги < n
#   GET    /GetAllUserIDBySatietyUnderN?n=           — user_id у кого сытость < n
#   GET    /GetAllUserIDByEnergyUnderN?n=            — user_id у кого энергия < n
#   GET    /GetAllUserIDByMoodUnderN?n=              — user_id у кого настроение < n

# ========================================


app = FastAPI()

conn = sqlite3.connect("pets.db", check_same_thread=False)
conn.row_factory = sqlite3.Row
cur = conn.cursor()


@app.post("/PostCreatePet/{user_id}", status_code=201)
def createPet(user_id: str, name: str):

    """Создать питомца. Если питомец уже существует — вернёт 409."""
    cur.execute("SELECT * FROM pets WHERE user_id = ?", (user_id,))
    if cur.fetchone():
        raise HTTPException(status_code=409, detail="Питомец уже существует")
    cur.execute("INSERT INTO pets (user_id, name) VALUES (?, ?)", (user_id, name))
    conn.commit()
    cur.execute("SELECT * FROM pets WHERE user_id = ?", (user_id,))
    return dict(cur.fetchone())

@app.delete("/DeletePetBy/{user_id}", status_code=204)
def deletePetByUserId(user_id: str):

    """Удалить питомца по user_id. Если питомец не найден — вернёт 404."""

    cur.execute("SELECT * FROM pets WHERE user_id = ?", (user_id,))
    if not cur.fetchone():
        raise HTTPException(status_code=404, detail="Питомец не найден")
    cur.execute("DELETE FROM pets WHERE user_id = ?", (user_id,))
    conn.commit()

@app.get("/GetPetBy/{user_id}")
def getPetByUserId(user_id: str):

    """Получить все данные питомца по user_id."""

    cur.execute("SELECT * FROM pets WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    return dict(row)

# ==================== MONEY ====================

@app.get("/GetMoney/{user_id}")
def getMoney(user_id: str):
    """Получить баланс денег питомца."""
    cur.execute("SELECT money FROM pets WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    return {"money": row["money"]}

@app.patch("/SetMoney/{user_id}")
def setMoney(user_id: str, amount: int):
    """Установить деньги (абсолютное значение)."""
    cur.execute("SELECT * FROM pets WHERE user_id = ?", (user_id,))
    if not cur.fetchone():
        raise HTTPException(status_code=404, detail="Питомец не найден")
    cur.execute("UPDATE pets SET money = ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    cur.execute("SELECT money FROM pets WHERE user_id = ?", (user_id,))
    return {"money": cur.fetchone()["money"]}




# ==================== NAME ====================

@app.get("/GetName/{user_id}")
def getName(user_id: str):
    """Получить имя питомца."""
    cur.execute("SELECT name FROM pets WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    return {"name": row["name"]}

@app.patch("/SetName/{user_id}")
def setName(user_id: str, name: str):
    """Изменить имя питомца (макс. 15 символов)."""
    if len(name) > 15:
        raise HTTPException(status_code=400, detail="Имя не должно превышать 15 символов")
    cur.execute("SELECT * FROM pets WHERE user_id = ?", (user_id,))
    if not cur.fetchone():
        raise HTTPException(status_code=404, detail="Питомец не найден")
    cur.execute("UPDATE pets SET name = ? WHERE user_id = ?", (name, user_id))
    conn.commit()
    return {"name": name}


# ==================== SATIETY ====================

@app.get("/GetSatiety/{user_id}")
def getSatiety(user_id: str):
    """Получить сытость питомца."""
    cur.execute("SELECT satiety FROM pets WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    return {"satiety": row["satiety"]}

@app.patch("/SetSatiety/{user_id}")
def setSatiety(user_id: str, value: int):
    """Установить сытость (0–100)."""
    if not (0 <= value <= 100):
        raise HTTPException(status_code=400, detail="Значение должно быть от 0 до 100")
    cur.execute("SELECT * FROM pets WHERE user_id = ?", (user_id,))
    if not cur.fetchone():
        raise HTTPException(status_code=404, detail="Питомец не найден")
    cur.execute("UPDATE pets SET satiety = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    return {"satiety": value}



# ==================== ENERGY ====================

@app.get("/GetEnergy/{user_id}")
def getEnergy(user_id: str):
    """Получить энергию питомца."""
    cur.execute("SELECT energy FROM pets WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    return {"energy": row["energy"]}

@app.patch("/SetEnergy/{user_id}")
def setEnergy(user_id: str, value: int):
    """Установить энергию (0–100)."""
    if not (0 <= value <= 100):
        raise HTTPException(status_code=400, detail="Значение должно быть от 0 до 100")
    cur.execute("SELECT * FROM pets WHERE user_id = ?", (user_id,))
    if not cur.fetchone():
        raise HTTPException(status_code=404, detail="Питомец не найден")
    cur.execute("UPDATE pets SET energy = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    return {"energy": value}




# ==================== MOOD ====================

@app.get("/GetMood/{user_id}")
def getMood(user_id: str):
    """Получить настроение питомца."""
    cur.execute("SELECT mood FROM pets WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    return {"mood": row["mood"]}

@app.patch("/SetMood/{user_id}")
def setMood(user_id: str, value: int):
    """Установить настроение (0–100)."""
    if not (0 <= value <= 100):
        raise HTTPException(status_code=400, detail="Значение должно быть от 0 до 100")
    cur.execute("SELECT * FROM pets WHERE user_id = ?", (user_id,))
    if not cur.fetchone():
        raise HTTPException(status_code=404, detail="Питомец не найден")
    cur.execute("UPDATE pets SET mood = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    return {"mood": value}




# ==================== STATES (JSON) ====================

@app.get("/GetStates/{user_id}")
def getStates(user_id: str):
    """Получить состояния питомца."""
    cur.execute("SELECT states FROM pets WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    return {"states": json.loads(row["states"]) if row["states"] else None}

@app.patch("/SetStates/{user_id}")
def setStates(user_id: str, states: dict):
    """Полностью заменить состояния питомца."""
    cur.execute("SELECT * FROM pets WHERE user_id = ?", (user_id,))
    if not cur.fetchone():
        raise HTTPException(status_code=404, detail="Питомец не найден")
    cur.execute("UPDATE pets SET states = ? WHERE user_id = ?", (json.dumps(states), user_id))
    conn.commit()
    return {"states": states}




# ==================== PET INVENTORY (JSON) ====================

@app.get("/GetPetInventory/{user_id}")
def getPetInventory(user_id: str):
    """Получить инвентарь питомца."""
    cur.execute("SELECT PetInventory FROM pets WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    return {"PetInventory": json.loads(row["PetInventory"]) if row["PetInventory"] else None}

@app.patch("/AddPetItem/{user_id}")
def addPetItem(user_id: str, item: str):
    """Добавить предмет в инвентарь питомца."""
    cur.execute("SELECT PetInventory FROM pets WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    inventory = json.loads(row["PetInventory"]) if row["PetInventory"] else []
    inventory.append(item)
    cur.execute("UPDATE pets SET PetInventory = ? WHERE user_id = ?", (json.dumps(inventory), user_id))
    conn.commit()
    return {"PetInventory": inventory}

@app.delete("/RemovePetItem/{user_id}")
def removePetItem(user_id: str, item: str):
    """Удалить предмет из инвентаря питомца."""
    cur.execute("SELECT PetInventory FROM pets WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    inventory = json.loads(row["PetInventory"]) if row["PetInventory"] else []
    if item not in inventory:
        raise HTTPException(status_code=404, detail=f"Предмет '{item}' не найден в инвентаре")
    inventory.remove(item)
    cur.execute("UPDATE pets SET PetInventory = ? WHERE user_id = ?", (json.dumps(inventory) if inventory else None, user_id))
    conn.commit()
    return {"PetInventory": inventory}


# ==================== USER INVENTORY (JSON) ====================

@app.get("/GetUserInventory/{user_id}")
def getUserInventory(user_id: str):
    """Получить инвентарь пользователя."""
    cur.execute("SELECT UserInventory FROM pets WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    return {"UserInventory": json.loads(row["UserInventory"]) if row["UserInventory"] else None}

@app.patch("/AddUserItem/{user_id}")
def addUserItem(user_id: str, item: str):
    """Добавить предмет в инвентарь пользователя."""
    cur.execute("SELECT UserInventory FROM pets WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    inventory = json.loads(row["UserInventory"]) if row["UserInventory"] else []
    inventory.append(item)
    cur.execute("UPDATE pets SET UserInventory = ? WHERE user_id = ?", (json.dumps(inventory), user_id))
    conn.commit()
    return {"UserInventory": inventory}

@app.delete("/RemoveUserItem/{user_id}")
def removeUserItem(user_id: str, item: str):
    """Удалить предмет из инвентаря пользователя."""
    cur.execute("SELECT UserInventory FROM pets WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    inventory = json.loads(row["UserInventory"]) if row["UserInventory"] else []
    if item not in inventory:
        raise HTTPException(status_code=404, detail=f"Предмет '{item}' не найден в инвентаре")
    inventory.remove(item)
    cur.execute("UPDATE pets SET UserInventory = ? WHERE user_id = ?", (json.dumps(inventory) if inventory else None, user_id))
    conn.commit()
    return {"UserInventory": inventory}


@app.get("/GetAllUserIDByMoneyUnderN")
def getAllUserIDByMoneyUnderN(n: int):
    """Получить user_id всех у кого деньги меньше N."""
    cur.execute("SELECT user_id, money FROM pets WHERE money < ?", (n,))
    rows = cur.fetchall()
    return {"users": [dict(row) for row in rows]}

@app.get("/GetAllUserIDBySatietyUnderN")
def getAllUserIDBySatietyUnderN(n: int):
    """Получить user_id всех у кого сытость меньше N."""
    cur.execute("SELECT user_id, satiety FROM pets WHERE satiety < ?", (n,))
    rows = cur.fetchall()
    return {"users": [dict(row) for row in rows]}

@app.get("/GetAllUserIDByEnergyUnderN")
def getAllUserIDByEnergyUnderN(n: int):
    """Получить user_id всех у кого энергия меньше N."""
    cur.execute("SELECT user_id, energy FROM pets WHERE energy < ?", (n,))
    rows = cur.fetchall()
    return {"users": [dict(row) for row in rows]}

@app.get("/GetAllUserIDByMoodUnderN")
def getAllUserIDByMoodUnderN(n: int):
    """Получить user_id всех у кого настроение меньше N."""
    cur.execute("SELECT user_id, mood FROM pets WHERE mood < ?", (n,))
    rows = cur.fetchall()
    return {"users": [dict(row) for row in rows]}\
    
@app.patch("/AllMoneyMinus/{user_id}")
def allMoneyMinus(user_id: str, n: int):
    """Вычесть n от денег (не уйдёт ниже 0)."""
    cur.execute("SELECT money FROM pets WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    new_value = max(0, row["money"] - n)
    cur.execute("UPDATE pets SET money = ? WHERE user_id = ?", (new_value, user_id))
    conn.commit()
    return {"money": new_value}

@app.patch("/AllSatietyMinus/{user_id}")
def allSatietyMinus(user_id: str, n: int):
    """Вычесть n от сытости (clamp 0–100)."""
    cur.execute("SELECT satiety FROM pets WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    new_value = max(0, min(100, row["satiety"] - n))
    cur.execute("UPDATE pets SET satiety = ? WHERE user_id = ?", (new_value, user_id))
    conn.commit()
    return {"satiety": new_value}

@app.patch("/AllEnergyMinus/{user_id}")
def allEnergyMinus(user_id: str, n: int):
    """Вычесть n от энергии (clamp 0–100)."""
    cur.execute("SELECT energy FROM pets WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    new_value = max(0, min(100, row["energy"] - n))
    cur.execute("UPDATE pets SET energy = ? WHERE user_id = ?", (new_value, user_id))
    conn.commit()
    return {"energy": new_value}

@app.patch("/AllMoodMinus/{user_id}")
def allMoodMinus(user_id: str, n: int):
    """Вычесть n от настроения (clamp 0–100)."""
    cur.execute("SELECT mood FROM pets WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    new_value = max(0, min(100, row["mood"] - n))
    cur.execute("UPDATE pets SET mood = ? WHERE user_id = ?", (new_value, user_id))
    conn.commit()
    return {"mood": new_value}

