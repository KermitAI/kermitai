# characters.py
"""
Character database for Paimon's Harem Discord bot.
Contains all character data and management functions.
"""

import json
import os
from typing import Dict, List, Tuple, Optional, Any

class CharacterDatabase:
    """Manages character data for the harem system."""
    
    def __init__(self, data_file: str = "character_database.json"):
        self.data_file = data_file
        self.characters: Dict[str, Dict[str, Any]] = {}
        self.load_characters()
    
    def load_characters(self):
        """Load character database from JSON file"""
        try:
            data_path = os.path.join(os.path.dirname(__file__), self.data_file)
            if os.path.exists(data_path):
                with open(data_path, 'r', encoding='utf-8') as f:
                    self.characters = json.load(f)
            else:
                # Create default database with sample characters
                self.characters = self.create_default_characters()
                self.save_characters()
        except Exception as e:
            print(f"Error loading characters: {e}")
            self.characters = self.create_default_characters()
    
    def save_characters(self):
        """Save character database to JSON file"""
        try:
            data_path = os.path.join(os.path.dirname(__file__), self.data_file)
            with open(data_path, 'w', encoding='utf-8') as f:
                json.dump(self.characters, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving characters: {e}")
    
    def create_default_characters(self) -> Dict[str, Dict[str, Any]]:
        """Create a default character database with popular anime characters"""
        characters = {}
        
        # Extended sample characters database
        sample_chars = [
            # Naruto
            {"name": "Naruto Uzumaki", "anime": "Naruto", "gender": "male", "rarity": "Legendary"},
            {"name": "Sasuke Uchiha", "anime": "Naruto", "gender": "male", "rarity": "Legendary"},
            {"name": "Sakura Haruno", "anime": "Naruto", "gender": "female", "rarity": "Epic"},
            {"name": "Hinata Hyuga", "anime": "Naruto", "gender": "female", "rarity": "Epic"},
            {"name": "Kakashi Hatake", "anime": "Naruto", "gender": "male", "rarity": "Legendary"},
            
            # Attack on Titan
            {"name": "Eren Yeager", "anime": "Attack on Titan", "gender": "male", "rarity": "Legendary"},
            {"name": "Mikasa Ackerman", "anime": "Attack on Titan", "gender": "female", "rarity": "Legendary"},
            {"name": "Levi Ackerman", "anime": "Attack on Titan", "gender": "male", "rarity": "Legendary"},
            {"name": "Armin Arlert", "anime": "Attack on Titan", "gender": "male", "rarity": "Epic"},
            {"name": "Historia Reiss", "anime": "Attack on Titan", "gender": "female", "rarity": "Epic"},
            
            # My Hero Academia
            {"name": "Izuku Midoriya", "anime": "My Hero Academia", "gender": "male", "rarity": "Legendary"},
            {"name": "Katsuki Bakugo", "anime": "My Hero Academia", "gender": "male", "rarity": "Legendary"},
            {"name": "Ochaco Uraraka", "anime": "My Hero Academia", "gender": "female", "rarity": "Epic"},
            {"name": "Shoto Todoroki", "anime": "My Hero Academia", "gender": "male", "rarity": "Legendary"},
            {"name": "Tsuyu Asui", "anime": "My Hero Academia", "gender": "female", "rarity": "Rare"},
            
            # Demon Slayer
            {"name": "Tanjiro Kamado", "anime": "Demon Slayer", "gender": "male", "rarity": "Legendary"},
            {"name": "Nezuko Kamado", "anime": "Demon Slayer", "gender": "female", "rarity": "Legendary"},
            {"name": "Zenitsu Agatsuma", "anime": "Demon Slayer", "gender": "male", "rarity": "Epic"},
            {"name": "Inosuke Hashibira", "anime": "Demon Slayer", "gender": "male", "rarity": "Epic"},
            {"name": "Shinobu Kocho", "anime": "Demon Slayer", "gender": "female", "rarity": "Legendary"},
            
            # One Piece
            {"name": "Monkey D. Luffy", "anime": "One Piece", "gender": "male", "rarity": "Legendary"},
            {"name": "Roronoa Zoro", "anime": "One Piece", "gender": "male", "rarity": "Legendary"},
            {"name": "Nami", "anime": "One Piece", "gender": "female", "rarity": "Epic"},
            {"name": "Nico Robin", "anime": "One Piece", "gender": "female", "rarity": "Epic"},
            {"name": "Sanji", "anime": "One Piece", "gender": "male", "rarity": "Epic"},
            
            # Genshin Impact
            {"name": "Paimon", "anime": "Genshin Impact", "gender": "female", "rarity": "Legendary"},
            {"name": "Lumine", "anime": "Genshin Impact", "gender": "female", "rarity": "Legendary"},
            {"name": "Aether", "anime": "Genshin Impact", "gender": "male", "rarity": "Legendary"},
            {"name": "Venti", "anime": "Genshin Impact", "gender": "male", "rarity": "Legendary"},
            {"name": "Diluc", "anime": "Genshin Impact", "gender": "male", "rarity": "Legendary"},

            # Dragon Ball Z
            {"name": "Goku", "anime": "Dragon Ball Z", "gender": "male", "rarity": "Legendary"},
            {"name": "Vegeta", "anime": "Dragon Ball Z", "gender": "male", "rarity": "Legendary"},
            {"name": "Gohan", "anime": "Dragon Ball Z", "gender": "male", "rarity": "Epic"},
            {"name": "Piccolo", "anime": "Dragon Ball Z", "gender": "male", "rarity": "Epic"},
            {"name": "Bulma", "anime": "Dragon Ball Z", "gender": "female", "rarity": "Rare"},
            
            # Fullmetal Alchemist: Brotherhood
            {"name": "Edward Elric", "anime": "Fullmetal Alchemist: Brotherhood", "gender": "male", "rarity": "Legendary"},
            {"name": "Alphonse Elric", "anime": "Fullmetal Alchemist: Brotherhood", "gender": "male", "rarity": "Epic"},
            {"name": "Winry Rockbell", "anime": "Fullmetal Alchemist: Brotherhood", "gender": "female", "rarity": "Epic"},
            {"name": "Roy Mustang", "anime": "Fullmetal Alchemist: Brotherhood", "gender": "male", "rarity": "Legendary"},
            {"name": "Riza Hawkeye", "anime": "Fullmetal Alchemist: Brotherhood", "gender": "female", "rarity": "Rare"},
            
            # Bleach
            {"name": "Ichigo Kurosaki", "anime": "Bleach", "gender": "male", "rarity": "Legendary"},
            {"name": "Rukia Kuchiki", "anime": "Bleach", "gender": "female", "rarity": "Epic"},
            {"name": "Renji Abarai", "anime": "Bleach", "gender": "male", "rarity": "Epic"},
            {"name": "Byakuya Kuchiki", "anime": "Bleach", "gender": "male", "rarity": "Legendary"},
            {"name": "Orihime Inoue", "anime": "Bleach", "gender": "female", "rarity": "Rare"},
            
            # Sword Art Online
            {"name": "Kirito", "anime": "Sword Art Online", "gender": "male", "rarity": "Legendary"},
            {"name": "Asuna", "anime": "Sword Art Online", "gender": "female", "rarity": "Legendary"},
            {"name": "Sinon", "anime": "Sword Art Online", "gender": "female", "rarity": "Epic"},
            {"name": "Leafa", "anime": "Sword Art Online", "gender": "female", "rarity": "Rare"},
            {"name": "Agil", "anime": "Sword Art Online", "gender": "male", "rarity": "Rare"},
            {"name": "Alice Zuberg", "anime": "Sword Art Online", "gender": "female", "rarity": "Legendary"},
            {"name": "Eugeo", "anime": "Sword Art Online", "gender": "male", "rarity": "Epic"},
            {"name": "Yui", "anime": "Sword Art Online", "gender": "female", "rarity": "Rare"},
            
            # One Punch Man
            {"name": "Saitama", "anime": "One Punch Man", "gender": "male", "rarity": "Legendary"},
            {"name": "Genos", "anime": "One Punch Man", "gender": "male", "rarity": "Epic"},
            {"name": "Tatsumaki", "anime": "One Punch Man", "gender": "female", "rarity": "Legendary"},
            {"name": "Bang", "anime": "One Punch Man", "gender": "male", "rarity": "Rare"},
            {"name": "King", "anime": "One Punch Man", "gender": "male", "rarity": "Rare"},
            
            # Tokyo Ghoul
            {"name": "Ken Kaneki", "anime": "Tokyo Ghoul", "gender": "male", "rarity": "Legendary"},
            {"name": "Touka Kirishima", "anime": "Tokyo Ghoul", "gender": "female", "rarity": "Epic"},
            {"name": "Yoshimura", "anime": "Tokyo Ghoul", "gender": "male", "rarity": "Rare"},
            {"name": "Rize Kamishiro", "anime": "Tokyo Ghoul", "gender": "female", "rarity": "Rare"},
            
            # JoJo's Bizarre Adventure
            {"name": "Jotaro Kujo", "anime": "JoJo's Bizarre Adventure", "gender": "male", "rarity": "Legendary"},
            {"name": "Josuke Higashikata", "anime": "JoJo's Bizarre Adventure", "gender": "male", "rarity": "Epic"},
            {"name": "Dio Brando", "anime": "JoJo's Bizarre Adventure", "gender": "male", "rarity": "Legendary"},
            {"name": "Rohan Kishibe", "anime": "JoJo's Bizarre Adventure", "gender": "male", "rarity": "Rare"},
            {"name": "Jolyne Cujoh", "anime": "JoJo's Bizarre Adventure", "gender": "female", "rarity": "Legendary"},

            # Jujutsu Kaisen
            {"name": "Yuji Itadori", "anime": "Jujutsu Kaisen", "gender": "male", "rarity": "Legendary"},
            {"name": "Megumi Fushiguro", "anime": "Jujutsu Kaisen", "gender": "male", "rarity": "Epic"},
            {"name": "Nobara Kugisaki", "anime": "Jujutsu Kaisen", "gender": "female", "rarity": "Epic"},
            {"name": "Satoru Gojo", "anime": "Jujutsu Kaisen", "gender": "male", "rarity": "Legendary"},
            {"name": "Suguru Geto", "anime": "Jujutsu Kaisen", "gender": "male", "rarity": "Epic"},

            # Death Note
            {"name": "Light Yagami", "anime": "Death Note", "gender": "male", "rarity": "Legendary"},
            {"name": "L", "anime": "Death Note", "gender": "male", "rarity": "Legendary"},
            {"name": "Misa Amane", "anime": "Death Note", "gender": "female", "rarity": "Epic"},
            {"name": "Near", "anime": "Death Note", "gender": "male", "rarity": "Rare"},
            {"name": "Ryuk", "anime": "Death Note", "gender": "male", "rarity": "Epic"},

            # Fairy Tail
            {"name": "Natsu Dragneel", "anime": "Fairy Tail", "gender": "male", "rarity": "Legendary"},
            {"name": "Lucy Heartfilia", "anime": "Fairy Tail", "gender": "female", "rarity": "Epic"},
            {"name": "Gray Fullbuster", "anime": "Fairy Tail", "gender": "male", "rarity": "Epic"},
            {"name": "Erza Scarlet", "anime": "Fairy Tail", "gender": "female", "rarity": "Legendary"},
            {"name": "Wendy Marvell", "anime": "Fairy Tail", "gender": "female", "rarity": "Rare"},

            # Black Clover
            {"name": "Asta", "anime": "Black Clover", "gender": "male", "rarity": "Legendary"},
            {"name": "Yuno", "anime": "Black Clover", "gender": "male", "rarity": "Epic"},
            {"name": "Noelle Silva", "anime": "Black Clover", "gender": "female", "rarity": "Epic"},
            {"name": "Mimosa Vermillion", "anime": "Black Clover", "gender": "female", "rarity": "Rare"},
            {"name": "Yami Sukehiro", "anime": "Black Clover", "gender": "male", "rarity": "Legendary"},

            # Hunter x Hunter
            {"name": "Gon Freecss", "anime": "Hunter x Hunter", "gender": "male", "rarity": "Legendary"},
            {"name": "Killua Zoldyck", "anime": "Hunter x Hunter", "gender": "male", "rarity": "Legendary"},
            {"name": "Kurapika", "anime": "Hunter x Hunter", "gender": "male", "rarity": "Epic"},
            {"name": "Leorio Paradinight", "anime": "Hunter x Hunter", "gender": "male", "rarity": "Rare"},
            {"name": "Hisoka", "anime": "Hunter x Hunter", "gender": "male", "rarity": "Epic"},

            # Re:Zero
            {"name": "Subaru Natsuki", "anime": "Re:Zero", "gender": "male", "rarity": "Epic"},
            {"name": "Emilia", "anime": "Re:Zero", "gender": "female", "rarity": "Legendary"},
            {"name": "Rem", "anime": "Re:Zero", "gender": "female", "rarity": "Legendary"},
            {"name": "Ram", "anime": "Re:Zero", "gender": "female", "rarity": "Epic"},
            {"name": "Beatrice", "anime": "Re:Zero", "gender": "female", "rarity": "Rare"},

            # The Rising of the Shield Hero
            {"name": "Naofumi Iwatani", "anime": "Shield Hero", "gender": "male", "rarity": "Legendary"},
            {"name": "Raphtalia", "anime": "Shield Hero", "gender": "female", "rarity": "Epic"},
            {"name": "Filo", "anime": "Shield Hero", "gender": "female", "rarity": "Rare"},
            {"name": "Melty", "anime": "Shield Hero", "gender": "female", "rarity": "Rare"},

            # Spy x Family
            {"name": "Loid Forger", "anime": "Spy x Family", "gender": "male", "rarity": "Epic"},
            {"name": "Yor Forger", "anime": "Spy x Family", "gender": "female", "rarity": "Epic"},
            {"name": "Anya Forger", "anime": "Spy x Family", "gender": "female", "rarity": "Rare"},
            {"name": "Bond", "anime": "Spy x Family", "gender": "male", "rarity": "Rare"},

            # Kakegurui
            {"name": "Yumeko Jabami", "anime": "Kakegurui", "gender": "female", "rarity": "Legendary"},
            {"name": "Mary Saotome", "anime": "Kakegurui", "gender": "female", "rarity": "Epic"},
            {"name": "Ryota Suzui", "anime": "Kakegurui", "gender": "male", "rarity": "Rare"},
            {"name": "Kirari Momobami", "anime": "Kakegurui", "gender": "female", "rarity": "Epic"},

            # Noragami
            {"name": "Yato", "anime": "Noragami", "gender": "male", "rarity": "Legendary"},
            {"name": "Hiyori Iki", "anime": "Noragami", "gender": "female", "rarity": "Epic"},
            {"name": "Yukine", "anime": "Noragami", "gender": "male", "rarity": "Epic"},

            # The Seven Deadly Sins
            {"name": "Meliodas", "anime": "The Seven Deadly Sins", "gender": "male", "rarity": "Legendary"},
            {"name": "Elizabeth Liones", "anime": "The Seven Deadly Sins", "gender": "female", "rarity": "Epic"},
            {"name": "Ban", "anime": "The Seven Deadly Sins", "gender": "male", "rarity": "Epic"},
            {"name": "Diane", "anime": "The Seven Deadly Sins", "gender": "female", "rarity": "Epic"},
            {"name": "Escanor", "anime": "The Seven Deadly Sins", "gender": "male", "rarity": "Legendary"},

            # Mob Psycho 100
            {"name": "Shigeo Kageyama (Mob)", "anime": "Mob Psycho 100", "gender": "male", "rarity": "Legendary"},
            {"name": "Reigen Arataka", "anime": "Mob Psycho 100", "gender": "male", "rarity": "Epic"},
            {"name": "Dimple", "anime": "Mob Psycho 100", "gender": "male", "rarity": "Rare"},
            {"name": "Ritsu Kageyama", "anime": "Mob Psycho 100", "gender": "male", "rarity": "Epic"},

            # Chainsaw Man
            {"name": "Denji", "anime": "Chainsaw Man", "gender": "male", "rarity": "Legendary"},
            {"name": "Power", "anime": "Chainsaw Man", "gender": "female", "rarity": "Legendary"},
            {"name": "Makima", "anime": "Chainsaw Man", "gender": "female", "rarity": "Epic"},
            {"name": "Aki Hayakawa", "anime": "Chainsaw Man", "gender": "male", "rarity": "Epic"},
            {"name": "Kishibe", "anime": "Chainsaw Man", "gender": "male", "rarity": "Rare"},

            # Blue Exorcist
            {"name": "Rin Okumura", "anime": "Blue Exorcist", "gender": "male", "rarity": "Legendary"},
            {"name": "Yukio Okumura", "anime": "Blue Exorcist", "gender": "male", "rarity": "Epic"},
            {"name": "Shiemi Moriyama", "anime": "Blue Exorcist", "gender": "female", "rarity": "Epic"},

            # Soul Eater
            {"name": "Maka Albarn", "anime": "Soul Eater", "gender": "female", "rarity": "Epic"},
            {"name": "Soul Eater Evans", "anime": "Soul Eater", "gender": "male", "rarity": "Epic"},
            {"name": "Death the Kid", "anime": "Soul Eater", "gender": "male", "rarity": "Epic"},
            {"name": "Black☆Star", "anime": "Soul Eater", "gender": "male", "rarity": "Rare"},
            {"name": "Tsubaki Nakatsukasa", "anime": "Soul Eater", "gender": "female", "rarity": "Rare"},

            # Seraph of the End
            {"name": "Yuuichirou Hyakuya", "anime": "Seraph of the End", "gender": "male", "rarity": "Epic"},
            {"name": "Mikaela Hyakuya", "anime": "Seraph of the End", "gender": "male", "rarity": "Epic"},
            {"name": "Shinoa Hiiragi", "anime": "Seraph of the End", "gender": "female", "rarity": "Epic"},
            {"name": "Guren Ichinose", "anime": "Seraph of the End", "gender": "male", "rarity": "Rare"},

            # Puella Magi Madoka Magica
            {"name": "Madoka Kaname", "anime": "Madoka Magica", "gender": "female", "rarity": "Legendary"},
            {"name": "Homura Akemi", "anime": "Madoka Magica", "gender": "female", "rarity": "Legendary"},
            {"name": "Sayaka Miki", "anime": "Madoka Magica", "gender": "female", "rarity": "Epic"},
            {"name": "Mami Tomoe", "anime": "Madoka Magica", "gender": "female", "rarity": "Epic"},
            {"name": "Kyoko Sakura", "anime": "Madoka Magica", "gender": "female", "rarity": "Epic"},

            # Assassination Classroom
            {"name": "Koro-sensei", "anime": "Assassination Classroom", "gender": "male", "rarity": "Legendary"},
            {"name": "Nagisa Shiota", "anime": "Assassination Classroom", "gender": "male", "rarity": "Epic"},
            {"name": "Karma Akabane", "anime": "Assassination Classroom", "gender": "male", "rarity": "Epic"},
            {"name": "Kaede Kayano", "anime": "Assassination Classroom", "gender": "female", "rarity": "Rare"},

            # Inuyasha
            {"name": "Inuyasha", "anime": "Inuyasha", "gender": "male", "rarity": "Legendary"},
            {"name": "Kagome Higurashi", "anime": "Inuyasha", "gender": "female", "rarity": "Epic"},
            {"name": "Sesshomaru", "anime": "Inuyasha", "gender": "male", "rarity": "Legendary"},
            {"name": "Kikyo", "anime": "Inuyasha", "gender": "female", "rarity": "Epic"},
            {"name": "Sango", "anime": "Inuyasha", "gender": "female", "rarity": "Rare"},

            # Sailor Moon
            {"name": "Usagi Tsukino (Sailor Moon)", "anime": "Sailor Moon", "gender": "female", "rarity": "Legendary"},
            {"name": "Ami Mizuno (Sailor Mercury)", "anime": "Sailor Moon", "gender": "female", "rarity": "Epic"},
            {"name": "Rei Hino (Sailor Mars)", "anime": "Sailor Moon", "gender": "female", "rarity": "Epic"},
            {"name": "Makoto Kino (Sailor Jupiter)", "anime": "Sailor Moon", "gender": "female", "rarity": "Epic"},
            {"name": "Minako Aino (Sailor Venus)", "anime": "Sailor Moon", "gender": "female", "rarity": "Epic"},

            # Yu Yu Hakusho
            {"name": "Yusuke Urameshi", "anime": "Yu Yu Hakusho", "gender": "male", "rarity": "Legendary"},
            {"name": "Hiei", "anime": "Yu Yu Hakusho", "gender": "male", "rarity": "Epic"},
            {"name": "Kurama", "anime": "Yu Yu Hakusho", "gender": "male", "rarity": "Epic"},
            {"name": "Kazuma Kuwabara", "anime": "Yu Yu Hakusho", "gender": "male", "rarity": "Rare"},
            {"name": "Botan", "anime": "Yu Yu Hakusho", "gender": "female", "rarity": "Rare"},

            # Toradora!
            {"name": "Taiga Aisaka", "anime": "Toradora!", "gender": "female", "rarity": "Legendary"},
            {"name": "Ryuuji Takasu", "anime": "Toradora!", "gender": "male", "rarity": "Epic"},
            {"name": "Minori Kushieda", "anime": "Toradora!", "gender": "female", "rarity": "Epic"},
            {"name": "Ami Kawashima", "anime": "Toradora!", "gender": "female", "rarity": "Rare"},

            # Elfen Lied
            {"name": "Lucy", "anime": "Elfen Lied", "gender": "female", "rarity": "Legendary"},
            {"name": "Kouta", "anime": "Elfen Lied", "gender": "male", "rarity": "Epic"},
            {"name": "Yuka", "anime": "Elfen Lied", "gender": "female", "rarity": "Rare"},

            # The Promised Neverland
            {"name": "Emma", "anime": "The Promised Neverland", "gender": "female", "rarity": "Epic"},
            {"name": "Norman", "anime": "The Promised Neverland", "gender": "male", "rarity": "Epic"},
            {"name": "Ray", "anime": "The Promised Neverland", "gender": "male", "rarity": "Epic"},
            {"name": "Isabella (The Mama)", "anime": "The Promised Neverland", "gender": "female", "rarity": "Rare"},

            # Your Name (Kimi no Na wa)
            {"name": "Taki Tachibana", "anime": "Your Name", "gender": "male", "rarity": "Epic"},
            {"name": "Mitsuha Miyamizu", "anime": "Your Name", "gender": "female", "rarity": "Epic"},

            # Violet Evergarden
            {"name": "Violet Evergarden", "anime": "Violet Evergarden", "gender": "female", "rarity": "Legendary"},
            {"name": "Gilbert Bougainvillea", "anime": "Violet Evergarden", "gender": "male", "rarity": "Epic"},
            {"name": "Claudia Hodgins", "anime": "Violet Evergarden", "gender": "male", "rarity": "Rare"},

            # Ergo Proxy
            {"name": "Re-l Mayer", "anime": "Ergo Proxy", "gender": "female", "rarity": "Epic"},
            {"name": "Vincent Law", "anime": "Ergo Proxy", "gender": "male", "rarity": "Epic"},

            # Akame ga Kill
            {"name": "Akame", "anime": "Akame ga Kill!", "gender": "female", "rarity": "Legendary"},
            {"name": "Tatsumi", "anime": "Akame ga Kill!", "gender": "male", "rarity": "Epic"},
            {"name": "Esdeath", "anime": "Akame ga Kill!", "gender": "female", "rarity": "Legendary"},
            {"name": "Mine", "anime": "Akame ga Kill!", "gender": "female", "rarity": "Epic"},
            {"name": "Leone", "anime": "Akame ga Kill!", "gender": "female", "rarity": "Epic"},

            # Angel Beats!
            {"name": "Otonashi Yuzuru", "anime": "Angel Beats!", "gender": "male", "rarity": "Epic"},
            {"name": "Kanade Tachibana", "anime": "Angel Beats!", "gender": "female", "rarity": "Legendary"},
            {"name": "Yuri Nakamura", "anime": "Angel Beats!", "gender": "female", "rarity": "Epic"},
            {"name": "Hinata Hideki", "anime": "Angel Beats!", "gender": "male", "rarity": "Rare"},

            # Clannad
            {"name": "Tomoya Okazaki", "anime": "Clannad", "gender": "male", "rarity": "Epic"},
            {"name": "Nagisa Furukawa", "anime": "Clannad", "gender": "female", "rarity": "Legendary"},
            {"name": "Kyou Fujibayashi", "anime": "Clannad", "gender": "female", "rarity": "Epic"},
            {"name": "Kotomi Ichinose", "anime": "Clannad", "gender": "female", "rarity": "Rare"},

            # Steins;Gate
            {"name": "Rintarou Okabe", "anime": "Steins;Gate", "gender": "male", "rarity": "Legendary"},
            {"name": "Kurisu Makise", "anime": "Steins;Gate", "gender": "female", "rarity": "Legendary"},
            {"name": "Mayuri Shiina", "anime": "Steins;Gate", "gender": "female", "rarity": "Epic"},
            {"name": "Itaru Hashida", "anime": "Steins;Gate", "gender": "male", "rarity": "Rare"},

            # The Quintessential Quintuplets
            {"name": "Itsuki Nakano", "anime": "The Quintessential Quintuplets", "gender": "female", "rarity": "Epic"},
            {"name": "Nino Nakano", "anime": "The Quintessential Quintuplets", "gender": "female", "rarity": "Epic"},
            {"name": "Miku Nakano", "anime": "The Quintessential Quintuplets", "gender": "female", "rarity": "Epic"},
            {"name": "Yotsuba Nakano", "anime": "The Quintessential Quintuplets", "gender": "female", "rarity": "Epic"},
            {"name": "Ichika Nakano", "anime": "The Quintessential Quintuplets", "gender": "female", "rarity": "Epic"},

            # That Time I Got Reincarnated as a Slime
            {"name": "Rimuru Tempest", "anime": "Slime Isekai", "gender": "male", "rarity": "Legendary"},
            {"name": "Milim Nava", "anime": "Slime Isekai", "gender": "female", "rarity": "Epic"},
            {"name": "Benimaru", "anime": "Slime Isekai", "gender": "male", "rarity": "Epic"},
            {"name": "Shion", "anime": "Slime Isekai", "gender": "female", "rarity": "Epic"},
            {"name": "Shuna", "anime": "Slime Isekai", "gender": "female", "rarity": "Rare"},

            # Konosuba
            {"name": "Kazuma Satou", "anime": "Konosuba", "gender": "male", "rarity": "Epic"},
            {"name": "Aqua", "anime": "Konosuba", "gender": "female", "rarity": "Legendary"},
            {"name": "Megumin", "anime": "Konosuba", "gender": "female", "rarity": "Legendary"},
            {"name": "Darkness", "anime": "Konosuba", "gender": "female", "rarity": "Epic"},

            # ReLIFE
            {"name": "Arata Kaizaki", "anime": "ReLIFE", "gender": "male", "rarity": "Epic"},
            {"name": "Chizuru Hishiro", "anime": "ReLIFE", "gender": "female", "rarity": "Epic"},
            {"name": "Rena Kariu", "anime": "ReLIFE", "gender": "female", "rarity": "Rare"},
            {"name": "Kazuomi Oga", "anime": "ReLIFE", "gender": "male", "rarity": "Rare"},

            # A Silent Voice
            {"name": "Shouya Ishida", "anime": "A Silent Voice", "gender": "male", "rarity": "Epic"},
            {"name": "Shouko Nishimiya", "anime": "A Silent Voice", "gender": "female", "rarity": "Legendary"},
            {"name": "Naoka Ueno", "anime": "A Silent Voice", "gender": "female", "rarity": "Rare"},

            # Your Lie in April
            {"name": "Kousei Arima", "anime": "Your Lie in April", "gender": "male", "rarity": "Epic"},
            {"name": "Kaori Miyazono", "anime": "Your Lie in April", "gender": "female", "rarity": "Legendary"},
            {"name": "Tsubaki Sawabe", "anime": "Your Lie in April", "gender": "female", "rarity": "Rare"},

            # Horimiya
            {"name": "Izumi Miyamura", "anime": "Horimiya", "gender": "male", "rarity": "Epic"},
            {"name": "Kyouko Hori", "anime": "Horimiya", "gender": "female", "rarity": "Epic"},
            {"name": "Yuki Yoshikawa", "anime": "Horimiya", "gender": "female", "rarity": "Rare"},
            {"name": "Toru Ishikawa", "anime": "Horimiya", "gender": "male", "rarity": "Rare"},

            # Fate Series (Fate/Stay Night, Fate/Zero, Fate/Grand Order)
            {"name": "Saber (Artoria Pendragon)", "anime": "Fate Series", "gender": "female", "rarity": "Legendary"},
            {"name": "Emiya Shirou", "anime": "Fate Series", "gender": "male", "rarity": "Epic"},
            {"name": "Rin Tohsaka", "anime": "Fate Series", "gender": "female", "rarity": "Epic"},
            {"name": "Illyasviel von Einzbern", "anime": "Fate Series", "gender": "female", "rarity": "Epic"},
            {"name": "Gilgamesh", "anime": "Fate Series", "gender": "male", "rarity": "Legendary"},
            {"name": "Kirei Kotomine", "anime": "Fate Series", "gender": "male", "rarity": "Rare"},
            {"name": "Iskandar (Rider)", "anime": "Fate/Zero", "gender": "male", "rarity": "Legendary"},
            {"name": "Mash Kyrielight", "anime": "Fate/Grand Order", "gender": "female", "rarity": "Epic"},

            # Studio Ghibli
            {"name": "Chihiro Ogino", "anime": "Spirited Away", "gender": "female", "rarity": "Legendary"},
            {"name": "Haku", "anime": "Spirited Away", "gender": "male", "rarity": "Epic"},
            {"name": "Howl", "anime": "Howl's Moving Castle", "gender": "male", "rarity": "Legendary"},
            {"name": "Sophie Hatter", "anime": "Howl's Moving Castle", "gender": "female", "rarity": "Epic"},
            {"name": "Kiki", "anime": "Kiki's Delivery Service", "gender": "female", "rarity": "Legendary"},
            {"name": "San", "anime": "Princess Mononoke", "gender": "female", "rarity": "Legendary"},
            {"name": "Ashitaka", "anime": "Princess Mononoke", "gender": "male", "rarity": "Epic"},
            {"name": "Pazu", "anime": "Castle in the Sky", "gender": "male", "rarity": "Epic"},
            {"name": "Sheeta", "anime": "Castle in the Sky", "gender": "female", "rarity": "Epic"},

            # Tokyo Revengers
            {"name": "Takemichi Hanagaki", "anime": "Tokyo Revengers", "gender": "male", "rarity": "Epic"},
            {"name": "Manjiro Sano (Mikey)", "anime": "Tokyo Revengers", "gender": "male", "rarity": "Legendary"},
            {"name": "Draken", "anime": "Tokyo Revengers", "gender": "male", "rarity": "Epic"},
            {"name": "Keisuke Baji", "anime": "Tokyo Revengers", "gender": "male", "rarity": "Epic"},
            {"name": "Emma Sano", "anime": "Tokyo Revengers", "gender": "female", "rarity": "Rare"},

            # Gintama
            {"name": "Gintoki Sakata", "anime": "Gintama", "gender": "male", "rarity": "Legendary"},
            {"name": "Shinpachi Shimura", "anime": "Gintama", "gender": "male", "rarity": "Rare"},
            {"name": "Kagura", "anime": "Gintama", "gender": "female", "rarity": "Epic"},
            {"name": "Toshiro Hijikata", "anime": "Gintama", "gender": "male", "rarity": "Epic"},
            {"name": "Sogo Okita", "anime": "Gintama", "gender": "male", "rarity": "Epic"},

            # Black Butler
            {"name": "Ciel Phantomhive", "anime": "Black Butler", "gender": "male", "rarity": "Epic"},
            {"name": "Sebastian Michaelis", "anime": "Black Butler", "gender": "male", "rarity": "Legendary"},
            {"name": "Grell Sutcliff", "anime": "Black Butler", "gender": "male", "rarity": "Epic"},
            {"name": "Elizabeth Midford", "anime": "Black Butler", "gender": "female", "rarity": "Rare"},

            # Devilman Crybaby
            {"name": "Akira Fudo", "anime": "Devilman Crybaby", "gender": "male", "rarity": "Legendary"},
            {"name": "Ryo Asuka", "anime": "Devilman Crybaby", "gender": "male", "rarity": "Legendary"},
            {"name": "Miki Makimura", "anime": "Devilman Crybaby", "gender": "female", "rarity": "Epic"},

            # Parasyte: The Maxim
            {"name": "Shinichi Izumi", "anime": "Parasyte", "gender": "male", "rarity": "Epic"},
            {"name": "Migi", "anime": "Parasyte", "gender": "male", "rarity": "Epic"},
            {"name": "Satomi Murano", "anime": "Parasyte", "gender": "female", "rarity": "Rare"},

            # Hellsing Ultimate
            {"name": "Alucard", "anime": "Hellsing", "gender": "male", "rarity": "Legendary"},
            {"name": "Integra Hellsing", "anime": "Hellsing", "gender": "female", "rarity": "Epic"},
            {"name": "Seras Victoria", "anime": "Hellsing", "gender": "female", "rarity": "Epic"},

            # Danganronpa (Anime)
            {"name": "Makoto Naegi", "anime": "Danganronpa", "gender": "male", "rarity": "Epic"},
            {"name": "Kyoko Kirigiri", "anime": "Danganronpa", "gender": "female", "rarity": "Epic"},
            {"name": "Junko Enoshima", "anime": "Danganronpa", "gender": "female", "rarity": "Legendary"},

            # Dr. Stone
            {"name": "Senku Ishigami", "anime": "Dr. Stone", "gender": "male", "rarity": "Legendary"},
            {"name": "Taiju Oki", "anime": "Dr. Stone", "gender": "male", "rarity": "Epic"},
            {"name": "Yuzuriha Ogawa", "anime": "Dr. Stone", "gender": "female", "rarity": "Rare"},
            {"name": "Tsukasa Shishio", "anime": "Dr. Stone", "gender": "male", "rarity": "Epic"},
            
            # Adding more Common rarity characters
            {"name": "Konohamaru", "anime": "Naruto", "gender": "male", "rarity": "Common"},
            {"name": "Tenten", "anime": "Naruto", "gender": "female", "rarity": "Common"},
            {"name": "Kiba Inuzuka", "anime": "Naruto", "gender": "male", "rarity": "Common"},
            {"name": "Shino Aburame", "anime": "Naruto", "gender": "male", "rarity": "Common"},
            {"name": "Ino Yamanaka", "anime": "Naruto", "gender": "female", "rarity": "Common"},
            
            {"name": "Chopper", "anime": "One Piece", "gender": "male", "rarity": "Rare"},
            {"name": "Usopp", "anime": "One Piece", "gender": "male", "rarity": "Rare"},
            {"name": "Franky", "anime": "One Piece", "gender": "male", "rarity": "Rare"},
            {"name": "Brook", "anime": "One Piece", "gender": "male", "rarity": "Rare"},
            {"name": "Jinbe", "anime": "One Piece", "gender": "male", "rarity": "Epic"},
            
            {"name": "Krillin", "anime": "Dragon Ball Z", "gender": "male", "rarity": "Common"},
            {"name": "Tien", "anime": "Dragon Ball Z", "gender": "male", "rarity": "Common"},
            {"name": "Yamcha", "anime": "Dragon Ball Z", "gender": "male", "rarity": "Common"},
            {"name": "Piccolo", "anime": "Dragon Ball Z", "gender": "male", "rarity": "Epic"},
            {"name": "Chi-Chi", "anime": "Dragon Ball Z", "gender": "female", "rarity": "Common"},
        ]

        for i, char in enumerate(sample_chars):
            char_id = str(i + 1)
            characters[char_id] = {
                "name": char["name"],
                "anime": char["anime"],
                "gender": char["gender"],
                "rarity": char["rarity"],
                "image_url": f"https://via.placeholder.com/300x400?text={char['name'].replace(' ', '+')}", # Placeholder
                "claimed_by": None,
                "married_to": None
            }
        
        return characters
    
    def get_character(self, char_id: str) -> Optional[Dict[str, Any]]:
        """Get a character by ID"""
        return self.characters.get(char_id)
    
    def get_all_characters(self) -> Dict[str, Dict[str, Any]]:
        """Get all characters"""
        return self.characters.copy()
    
    def get_available_characters(self, gender: Optional[str] = None) -> List[Tuple[str, Dict[str, Any]]]:
        """Get list of available (unclaimed) characters"""
        available = []
        for char_id, char in self.characters.items():
            if char["claimed_by"] is None:
                if gender is None or char["gender"] == gender:
                    available.append((char_id, char))
        return available
    
    def get_characters_by_owner(self, owner_id: int) -> List[Tuple[str, Dict[str, Any]]]:
        """Get all characters owned by a specific user"""
        owned = []
        for char_id, char in self.characters.items():
            if char["claimed_by"] == owner_id:
                owned.append((char_id, char))
        return owned
    
    def get_characters_by_anime(self, anime: str) -> List[Tuple[str, Dict[str, Any]]]:
        """Get all characters from a specific anime"""
        anime_chars = []
        for char_id, char in self.characters.items():
            if char["anime"].lower() == anime.lower():
                anime_chars.append((char_id, char))
        return anime_chars
    
    def get_characters_by_rarity(self, rarity: str) -> List[Tuple[str, Dict[str, Any]]]:
        """Get all characters of a specific rarity"""
        rarity_chars = []
        for char_id, char in self.characters.items():
            if char["rarity"].lower() == rarity.lower():
                rarity_chars.append((char_id, char))
        return rarity_chars
    
    def search_characters(self, query: str) -> List[Tuple[str, Dict[str, Any]]]:
        """Search for characters by name or anime"""
        results = []
        query_lower = query.lower()
        for char_id, char in self.characters.items():
            if (query_lower in char["name"].lower() or 
                query_lower in char["anime"].lower()):
                results.append((char_id, char))
        return results
    
    def claim_character(self, char_id: str, owner_id: int) -> bool:
        """Claim a character for a user"""
        if char_id in self.characters and self.characters[char_id]["claimed_by"] is None:
            self.characters[char_id]["claimed_by"] = owner_id
            self.save_characters()
            return True
        return False
    
    def release_character(self, char_id: str) -> bool:
        """Release a character back to the pool"""
        if char_id in self.characters:
            self.characters[char_id]["claimed_by"] = None
            self.characters[char_id]["married_to"] = None
            self.save_characters()
            return True
        return False
    
    def marry_character(self, char_id: str, user_id: int) -> bool:
        """Marry a character to a user"""
        if (char_id in self.characters and 
            self.characters[char_id]["claimed_by"] == user_id):
            self.characters[char_id]["married_to"] = user_id
            self.save_characters()
            return True
        return False
    
    def divorce_character(self, char_id: str) -> bool:
        """Divorce a character"""
        if char_id in self.characters:
            self.characters[char_id]["married_to"] = None
            self.save_characters()
            return True
        return False
    
    def add_character(self, name: str, anime: str, gender: str, rarity: str, image_url: str = "") -> str:
        """Add a new character to the database"""
        # Find next available ID
        max_id = 0
        for char_id in self.characters.keys():
            try:
                id_num = int(char_id)
                if id_num > max_id:
                    max_id = id_num
            except ValueError:
                continue
        
        new_id = str(max_id + 1)
        
        self.characters[new_id] = {
            "name": name,
            "anime": anime,
            "gender": gender,
            "rarity": rarity,
            "image_url": image_url or f"https://via.placeholder.com/300x400?text={name.replace(' ', '+')}",
            "claimed_by": None,
            "married_to": None
        }
        
        self.save_characters()
        return new_id
    
    def remove_character(self, char_id: str) -> bool:
        """Remove a character from the database"""
        if char_id in self.characters:
            del self.characters[char_id]
            self.save_characters()
            return True
        return False
    
    def update_character(self, char_id: str, **kwargs) -> bool:
        """Update character attributes"""
        if char_id in self.characters:
            for key, value in kwargs.items():
                if key in self.characters[char_id]:
                    self.characters[char_id][key] = value
            self.save_characters()
            return True
        return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics"""
        total = len(self.characters)
        claimed = sum(1 for char in self.characters.values() if char["claimed_by"] is not None)
        married = sum(1 for char in self.characters.values() if char["married_to"] is not None)
        
        rarity_counts = {}
        gender_counts = {}
        anime_counts = {}
        
        for char in self.characters.values():
            # Count by rarity
            rarity = char["rarity"]
            rarity_counts[rarity] = rarity_counts.get(rarity, 0) + 1
            
            # Count by gender
            gender = char["gender"]
            gender_counts[gender] = gender_counts.get(gender, 0) + 1
            
            # Count by anime
            anime = char["anime"]
            anime_counts[anime] = anime_counts.get(anime, 0) + 1
        
        return {
            "total_characters": total,
            "claimed_characters": claimed,
            "available_characters": total - claimed,
            "married_characters": married,
            "rarity_distribution": rarity_counts,
            "gender_distribution": gender_counts,
            "anime_distribution": anime_counts
        }