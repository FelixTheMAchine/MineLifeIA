"""Seleciona alimentos reais observados, sem confundir componente com segurança nutricional."""
import math


UNSAFE_VANILLA_FOOD = {
    'minecraft:rotten_flesh', 'minecraft:spider_eye', 'minecraft:poisonous_potato',
    'minecraft:pufferfish', 'minecraft:raw_chicken', 'minecraft:chorus_fruit',
}


class FoodAcquisitionManager:
    def safe_id(self, item_id):
        return item_id.startswith('minecraft:') and item_id not in UNSAFE_VANILLA_FOOD

    def choose(self, observations, player, inventory, threshold=6):
        if player.danger or player.food > threshold:
            return None
        candidates = []
        for item in observations:
            if not item.edible or not self.safe_id(item.item_id):
                continue
            distance = math.dist((player.x, player.y, player.z), (item.x, item.y, item.z))
            if distance > 12:
                continue
            candidates.append((distance, -item.count, item.entity_id.int, item))
        return min(candidates, default=(None, None, None, None), key=lambda row: row[:3])[3]

    def choose_resource(self, observations, player, inventory):
        useful = {'minecraft:wheat_seeds', 'minecraft:beetroot_seeds', 'minecraft:melon_seeds',
                  'minecraft:pumpkin_seeds', 'minecraft:oak_log', 'minecraft:birch_log',
                  'minecraft:spruce_log', 'minecraft:jungle_log', 'minecraft:acacia_log',
                  'minecraft:dark_oak_log', 'minecraft:mangrove_log', 'minecraft:cherry_log',
                  'minecraft:oak_planks', 'minecraft:birch_planks', 'minecraft:stick',
                  'minecraft:cobblestone', 'minecraft:stone', 'minecraft:coal', 'minecraft:raw_iron',
                  'minecraft:iron_ingot', 'minecraft:string', 'minecraft:bone', 'minecraft:torch'}
        candidates = []
        for item in observations:
            if item.item_id not in useful or inventory.get(item.item_id, 0) >= 16:
                continue
            distance = math.dist((player.x, player.y, player.z), (item.x, item.y, item.z))
            if distance <= 10:
                candidates.append((distance, item.entity_id.int, item))
        return min(candidates, default=(None, None, None), key=lambda row: row[:2])[2]
