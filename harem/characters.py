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
            {"name": "Naruto Uzumaki", "anime": "Naruto", "gender": "male", "rarity": "legendary"},
            {"name": "Sasuke Uchiha", "anime": "Naruto", "gender": "male", "rarity": "legendary"},
            {"name": "Sakura Haruno", "anime": "Naruto", "gender": "female", "rarity": "epic"},
            {"name": "Hinata Hyuga", "anime": "Naruto", "gender": "female", "rarity": "epic"},
            {"name": "Kakashi Hatake", "anime": "Naruto", "gender": "male", "rarity": "legendary"},
            
            # Attack on Titan
            {"name": "Eren Yeager", "anime": "Attack on Titan", "gender": "male", "rarity": "legendary"},
            {"name": "Mikasa Ackerman", "anime": "Attack on Titan", "gender": "female", "rarity": "legendary"},
            {"name": "Levi Ackerman", "anime": "Attack on Titan", "gender": "male", "rarity": "legendary"},
            {"name": "Armin Arlert", "anime": "Attack on Titan", "gender": "male", "rarity": "epic"},
            {"name": "Historia Reiss", "anime": "Attack on Titan", "gender": "female", "rarity": "epic"},
            
            # My Hero Academia
            {"name": "Izuku Midoriya", "anime": "My Hero Academia", "gender": "male", "rarity": "legendary"},
            {"name": "Katsuki Bakugo", "anime": "My Hero Academia", "gender": "male", "rarity": "legendary"},
            {"name": "Ochaco Uraraka", "anime": "My Hero Academia", "gender": "female", "rarity": "epic"},
            {"name": "Shoto Todoroki", "anime": "My Hero Academia", "gender": "male", "rarity": "legendary"},
            {"name": "Tsuyu Asui", "anime": "My Hero Academia", "gender": "female", "rarity": "rare"},
            
            # Demon Slayer
            {"name": "Tanjiro Kamado", "anime": "Demon Slayer", "gender": "male", "rarity": "legendary"},
            {"name": "Nezuko Kamado", "anime": "Demon Slayer", "gender": "female", "rarity": "legendary"},
            {"name": "Zenitsu Agatsuma", "anime": "Demon Slayer", "gender": "male", "rarity": "epic"},
            {"name": "Inosuke Hashibira", "anime": "Demon Slayer", "gender": "male", "rarity": "epic"},
            {"name": "Shinobu Kocho", "anime": "Demon Slayer", "gender": "female", "rarity": "legendary"},
            
            # One Piece
            {"name": "Monkey D. Luffy", "anime": "One Piece", "gender": "male", "rarity": "legendary"},
            {"name": "Roronoa Zoro", "anime": "One Piece", "gender": "male", "rarity": "legendary"},
            {"name": "Nami", "anime": "One Piece", "gender": "female", "rarity": "epic"},
            {"name": "Nico Robin", "anime": "One Piece", "gender": "female", "rarity": "epic"},
            {"name": "Sanji", "anime": "One Piece", "gender": "male", "rarity": "epic"},
            
            # Genshin Impact
            {"name": "Paimon", "anime": "Genshin Impact", "gender": "female", "rarity": "legendary"},
            {"name": "Lumine", "anime": "Genshin Impact", "gender": "female", "rarity": "legendary"},
            {"name": "Aether", "anime": "Genshin Impact", "gender": "male", "rarity": "legendary"},
            {"name": "Venti", "anime": "Genshin Impact", "gender": "male", "rarity": "legendary"},
            {"name": "Diluc", "anime": "Genshin Impact", "gender": "male", "rarity": "legendary"},

            # Dragon Ball Z
            {"name": "Goku", "anime": "Dragon Ball Z", "gender": "male", "rarity": "legendary"},
            {"name": "Vegeta", "anime": "Dragon Ball Z", "gender": "male", "rarity": "legendary"},
            {"name": "Gohan", "anime": "Dragon Ball Z", "gender": "male", "rarity": "epic"},
            {"name": "Piccolo", "anime": "Dragon Ball Z", "gender": "male", "rarity": "epic"},
            {"name": "Bulma", "anime": "Dragon Ball Z", "gender": "female", "rarity": "rare"},
            
            # Fullmetal Alchemist: Brotherhood
            {"name": "Edward Elric", "anime": "Fullmetal Alchemist: Brotherhood", "gender": "male", "rarity": "legendary"},
            {"name": "Alphonse Elric", "anime": "Fullmetal Alchemist: Brotherhood", "gender": "male", "rarity": "epic"},
            {"name": "Winry Rockbell", "anime": "Fullmetal Alchemist: Brotherhood", "gender": "female", "rarity": "epic"},
            {"name": "Roy Mustang", "anime": "Fullmetal Alchemist: Brotherhood", "gender": "male", "rarity": "legendary"},
            {"name": "Riza Hawkeye", "anime": "Fullmetal Alchemist: Brotherhood", "gender": "female", "rarity": "rare"},
            
            # Bleach
            {"name": "Ichigo Kurosaki", "anime": "Bleach", "gender": "male", "rarity": "legendary"},
            {"name": "Rukia Kuchiki", "anime": "Bleach", "gender": "female", "rarity": "epic"},
            {"name": "Renji Abarai", "anime": "Bleach", "gender": "male", "rarity": "epic"},
            {"name": "Byakuya Kuchiki", "anime": "Bleach", "gender": "male", "rarity": "legendary"},
            {"name": "Orihime Inoue", "anime": "Bleach", "gender": "female", "rarity": "rare"},
            
            # Sword Art Online
            {"name": "Kirito", "anime": "Sword Art Online", "gender": "male", "rarity": "legendary"},
            {"name": "Asuna", "anime": "Sword Art Online", "gender": "female", "rarity": "legendary"},
            {"name": "Sinon", "anime": "Sword Art Online", "gender": "female", "rarity": "epic"},
            {"name": "Leafa", "anime": "Sword Art Online", "gender": "female", "rarity": "rare"},
            {"name": "Agil", "anime": "Sword Art Online", "gender": "male", "rarity": "rare"},
            {"name": "Alice Zuberg", "anime": "Sword Art Online", "gender": "female", "rarity": "legendary"},
            {"name": "Eugeo", "anime": "Sword Art Online", "gender": "male", "rarity": "epic"},
            {"name": "Yui", "anime": "Sword Art Online", "gender": "female", "rarity": "rare"},
            
            # One Punch Man
            {"name": "Saitama", "anime": "One Punch Man", "gender": "male", "rarity": "legendary"},
            {"name": "Genos", "anime": "One Punch Man", "gender": "male", "rarity": "epic"},
            {"name": "Tatsumaki", "anime": "One Punch Man", "gender": "female", "rarity": "legendary"},
            {"name": "Bang", "anime": "One Punch Man", "gender": "male", "rarity": "rare"},
            {"name": "King", "anime": "One Punch Man", "gender": "male", "rarity": "rare"},
            
            # Tokyo Ghoul
            {"name": "Ken Kaneki", "anime": "Tokyo Ghoul", "gender": "male", "rarity": "legendary"},
            {"name": "Touka Kirishima", "anime": "Tokyo Ghoul", "gender": "female", "rarity": "epic"},
            {"name": "Yoshimura", "anime": "Tokyo Ghoul", "gender": "male", "rarity": "rare"},
            {"name": "Rize Kamishiro", "anime": "Tokyo Ghoul", "gender": "female", "rarity": "rare"},
            
            # JoJo's Bizarre Adventure
            {"name": "Jotaro Kujo", "anime": "JoJo's Bizarre Adventure", "gender": "male", "rarity": "legendary"},
            {"name": "Josuke Higashikata", "anime": "JoJo's Bizarre Adventure", "gender": "male", "rarity": "epic"},
            {"name": "Dio Brando", "anime": "JoJo's Bizarre Adventure", "gender": "male", "rarity": "legendary"},
            {"name": "Rohan Kishibe", "anime": "JoJo's Bizarre Adventure", "gender": "male", "rarity": "rare"},
            {"name": "Jolyne Cujoh", "anime": "JoJo's Bizarre Adventure", "gender": "female", "rarity": "legendary"},

            # Jujutsu Kaisen
            {"name": "Yuji Itadori", "anime": "Jujutsu Kaisen", "gender": "male", "rarity": "legendary"},
            {"name": "Megumi Fushiguro", "anime": "Jujutsu Kaisen", "gender": "male", "rarity": "epic"},
            {"name": "Nobara Kugisaki", "anime": "Jujutsu Kaisen", "gender": "female", "rarity": "epic"},
            {"name": "Satoru Gojo", "anime": "Jujutsu Kaisen", "gender": "male", "rarity": "legendary"},
            {"name": "Suguru Geto", "anime": "Jujutsu Kaisen", "gender": "male", "rarity": "epic"},

            # Death Note
            {"name": "Light Yagami", "anime": "Death Note", "gender": "male", "rarity": "legendary"},
            {"name": "L", "anime": "Death Note", "gender": "male", "rarity": "legendary"},
            {"name": "Misa Amane", "anime": "Death Note", "gender": "female", "rarity": "epic"},
            {"name": "Near", "anime": "Death Note", "gender": "male", "rarity": "rare"},
            {"name": "Ryuk", "anime": "Death Note", "gender": "male", "rarity": "epic"},

            # Fairy Tail
            {"name": "Natsu Dragneel", "anime": "Fairy Tail", "gender": "male", "rarity": "legendary"},
            {"name": "Lucy Heartfilia", "anime": "Fairy Tail", "gender": "female", "rarity": "epic"},
            {"name": "Gray Fullbuster", "anime": "Fairy Tail", "gender": "male", "rarity": "epic"},
            {"name": "Erza Scarlet", "anime": "Fairy Tail", "gender": "female", "rarity": "legendary"},
            {"name": "Wendy Marvell", "anime": "Fairy Tail", "gender": "female", "rarity": "rare"},

            # Black Clover
            {"name": "Asta", "anime": "Black Clover", "gender": "male", "rarity": "legendary"},
            {"name": "Yuno", "anime": "Black Clover", "gender": "male", "rarity": "epic"},
            {"name": "Noelle Silva", "anime": "Black Clover", "gender": "female", "rarity": "epic"},
            {"name": "Mimosa Vermillion", "anime": "Black Clover", "gender": "female", "rarity": "rare"},
            {"name": "Yami Sukehiro", "anime": "Black Clover", "gender": "male", "rarity": "legendary"},

            # Hunter x Hunter
            {"name": "Gon Freecss", "anime": "Hunter x Hunter", "gender": "male", "rarity": "legendary"},
            {"name": "Killua Zoldyck", "anime": "Hunter x Hunter", "gender": "male", "rarity": "legendary"},
            {"name": "Kurapika", "anime": "Hunter x Hunter", "gender": "male", "rarity": "epic"},
            {"name": "Leorio Paradinight", "anime": "Hunter x Hunter", "gender": "male", "rarity": "rare"},
            {"name": "Hisoka", "anime": "Hunter x Hunter", "gender": "male", "rarity": "epic"},

            # Re:Zero
            {"name": "Subaru Natsuki", "anime": "Re:Zero", "gender": "male", "rarity": "epic"},
            {"name": "Emilia", "anime": "Re:Zero", "gender": "female", "rarity": "legendary"},
            {"name": "Rem", "anime": "Re:Zero", "gender": "female", "rarity": "legendary"},
            {"name": "Ram", "anime": "Re:Zero", "gender": "female", "rarity": "epic"},
            {"name": "Beatrice", "anime": "Re:Zero", "gender": "female", "rarity": "rare"},

            # The Rising of the Shield Hero
            {"name": "Naofumi Iwatani", "anime": "Shield Hero", "gender": "male", "rarity": "legendary"},
            {"name": "Raphtalia", "anime": "Shield Hero", "gender": "female", "rarity": "epic"},
            {"name": "Filo", "anime": "Shield Hero", "gender": "female", "rarity": "rare"},
            {"name": "Melty", "anime": "Shield Hero", "gender": "female", "rarity": "rare"},

            # Spy x Family
            {"name": "Loid Forger", "anime": "Spy x Family", "gender": "male", "rarity": "epic"},
            {"name": "Yor Forger", "anime": "Spy x Family", "gender": "female", "rarity": "epic"},
            {"name": "Anya Forger", "anime": "Spy x Family", "gender": "female", "rarity": "rare"},
            {"name": "Bond", "anime": "Spy x Family", "gender": "male", "rarity": "rare"},

            # Kakegurui
            {"name": "Yumeko Jabami", "anime": "Kakegurui", "gender": "female", "rarity": "legendary"},
            {"name": "Mary Saotome", "anime": "Kakegurui", "gender": "female", "rarity": "epic"},
            {"name": "Ryota Suzui", "anime": "Kakegurui", "gender": "male", "rarity": "rare"},
            {"name": "Kirari Momobami", "anime": "Kakegurui", "gender": "female", "rarity": "epic"},

            # Noragami
            {"name": "Yato", "anime": "Noragami", "gender": "male", "rarity": "legendary"},
            {"name": "Hiyori Iki", "anime": "Noragami", "gender": "female", "rarity": "epic"},
            {"name": "Yukine", "anime": "Noragami", "gender": "male", "rarity": "epic"},

            # The Seven Deadly Sins
            {"name": "Meliodas", "anime": "The Seven Deadly Sins", "gender": "male", "rarity": "legendary"},
            {"name": "Elizabeth Liones", "anime": "The Seven Deadly Sins", "gender": "female", "rarity": "epic"},
            {"name": "Ban", "anime": "The Seven Deadly Sins", "gender": "male", "rarity": "epic"},
            {"name": "Diane", "anime": "The Seven Deadly Sins", "gender": "female", "rarity": "epic"},
            {"name": "Escanor", "anime": "The Seven Deadly Sins", "gender": "male", "rarity": "legendary"},

            # Mob Psycho 100
            {"name": "Shigeo Kageyama (Mob)", "anime": "Mob Psycho 100", "gender": "male", "rarity": "legendary"},
            {"name": "Reigen Arataka", "anime": "Mob Psycho 100", "gender": "male", "rarity": "epic"},
            {"name": "Dimple", "anime": "Mob Psycho 100", "gender": "male", "rarity": "rare"},
            {"name": "Ritsu Kageyama", "anime": "Mob Psycho 100", "gender": "male", "rarity": "epic"},

            # Chainsaw Man
            {"name": "Denji", "anime": "Chainsaw Man", "gender": "male", "rarity": "legendary"},
            {"name": "Power", "anime": "Chainsaw Man", "gender": "female", "rarity": "legendary"},
            {"name": "Makima", "anime": "Chainsaw Man", "gender": "female", "rarity": "epic"},
            {"name": "Aki Hayakawa", "anime": "Chainsaw Man", "gender": "male", "rarity": "epic"},
            {"name": "Kishibe", "anime": "Chainsaw Man", "gender": "male", "rarity": "rare"},

            # Blue Exorcist
            {"name": "Rin Okumura", "anime": "Blue Exorcist", "gender": "male", "rarity": "legendary"},
            {"name": "Yukio Okumura", "anime": "Blue Exorcist", "gender": "male", "rarity": "epic"},
            {"name": "Shiemi Moriyama", "anime": "Blue Exorcist", "gender": "female", "rarity": "epic"},

            # Soul Eater
            {"name": "Maka Albarn", "anime": "Soul Eater", "gender": "female", "rarity": "epic"},
            {"name": "Soul Eater Evans", "anime": "Soul Eater", "gender": "male", "rarity": "epic"},
            {"name": "Death the Kid", "anime": "Soul Eater", "gender": "male", "rarity": "epic"},
            {"name": "Black☆Star", "anime": "Soul Eater", "gender": "male", "rarity": "rare"},
            {"name": "Tsubaki Nakatsukasa", "anime": "Soul Eater", "gender": "female", "rarity": "rare"},

            # Seraph of the End
            {"name": "Yuuichirou Hyakuya", "anime": "Seraph of the End", "gender": "male", "rarity": "epic"},
            {"name": "Mikaela Hyakuya", "anime": "Seraph of the End", "gender": "male", "rarity": "epic"},
            {"name": "Shinoa Hiiragi", "anime": "Seraph of the End", "gender": "female", "rarity": "epic"},
            {"name": "Guren Ichinose", "anime": "Seraph of the End", "gender": "male", "rarity": "rare"},

            # Puella Magi Madoka Magica
            {"name": "Madoka Kaname", "anime": "Madoka Magica", "gender": "female", "rarity": "legendary"},
            {"name": "Homura Akemi", "anime": "Madoka Magica", "gender": "female", "rarity": "legendary"},
            {"name": "Sayaka Miki", "anime": "Madoka Magica", "gender": "female", "rarity": "epic"},
            {"name": "Mami Tomoe", "anime": "Madoka Magica", "gender": "female", "rarity": "epic"},
            {"name": "Kyoko Sakura", "anime": "Madoka Magica", "gender": "female", "rarity": "epic"},

            # Assassination Classroom
            {"name": "Koro-sensei", "anime": "Assassination Classroom", "gender": "male", "rarity": "legendary"},
            {"name": "Nagisa Shiota", "anime": "Assassination Classroom", "gender": "male", "rarity": "epic"},
            {"name": "Karma Akabane", "anime": "Assassination Classroom", "gender": "male", "rarity": "epic"},
            {"name": "Kaede Kayano", "anime": "Assassination Classroom", "gender": "female", "rarity": "rare"},

            # Inuyasha
            {"name": "Inuyasha", "anime": "Inuyasha", "gender": "male", "rarity": "legendary"},
            {"name": "Kagome Higurashi", "anime": "Inuyasha", "gender": "female", "rarity": "epic"},
            {"name": "Sesshomaru", "anime": "Inuyasha", "gender": "male", "rarity": "legendary"},
            {"name": "Kikyo", "anime": "Inuyasha", "gender": "female", "rarity": "epic"},
            {"name": "Sango", "anime": "Inuyasha", "gender": "female", "rarity": "rare"},

            # Sailor Moon
            {"name": "Usagi Tsukino (Sailor Moon)", "anime": "Sailor Moon", "gender": "female", "rarity": "legendary"},
            {"name": "Ami Mizuno (Sailor Mercury)", "anime": "Sailor Moon", "gender": "female", "rarity": "epic"},
            {"name": "Rei Hino (Sailor Mars)", "anime": "Sailor Moon", "gender": "female", "rarity": "epic"},
            {"name": "Makoto Kino (Sailor Jupiter)", "anime": "Sailor Moon", "gender": "female", "rarity": "epic"},
            {"name": "Minako Aino (Sailor Venus)", "anime": "Sailor Moon", "gender": "female", "rarity": "epic"},

            # Yu Yu Hakusho
            {"name": "Yusuke Urameshi", "anime": "Yu Yu Hakusho", "gender": "male", "rarity": "legendary"},
            {"name": "Hiei", "anime": "Yu Yu Hakusho", "gender": "male", "rarity": "epic"},
            {"name": "Kurama", "anime": "Yu Yu Hakusho", "gender": "male", "rarity": "epic"},
            {"name": "Kazuma Kuwabara", "anime": "Yu Yu Hakusho", "gender": "male", "rarity": "rare"},
            {"name": "Botan", "anime": "Yu Yu Hakusho", "gender": "female", "rarity": "rare"},

            # Toradora!
            {"name": "Taiga Aisaka", "anime": "Toradora!", "gender": "female", "rarity": "legendary"},
            {"name": "Ryuuji Takasu", "anime": "Toradora!", "gender": "male", "rarity": "epic"},
            {"name": "Minori Kushieda", "anime": "Toradora!", "gender": "female", "rarity": "epic"},
            {"name": "Ami Kawashima", "anime": "Toradora!", "gender": "female", "rarity": "rare"},

            # Elfen Lied
            {"name": "Lucy", "anime": "Elfen Lied", "gender": "female", "rarity": "legendary"},
            {"name": "Kouta", "anime": "Elfen Lied", "gender": "male", "rarity": "epic"},
            {"name": "Yuka", "anime": "Elfen Lied", "gender": "female", "rarity": "rare"},

            # The Promised Neverland
            {"name": "Emma", "anime": "The Promised Neverland", "gender": "female", "rarity": "epic"},
            {"name": "Norman", "anime": "The Promised Neverland", "gender": "male", "rarity": "epic"},
            {"name": "Ray", "anime": "The Promised Neverland", "gender": "male", "rarity": "epic"},
            {"name": "Isabella (The Mama)", "anime": "The Promised Neverland", "gender": "female", "rarity": "rare"},

            # Your Name (Kimi no Na wa)
            {"name": "Taki Tachibana", "anime": "Your Name", "gender": "male", "rarity": "epic"},
            {"name": "Mitsuha Miyamizu", "anime": "Your Name", "gender": "female", "rarity": "epic"},

            # Violet Evergarden
            {"name": "Violet Evergarden", "anime": "Violet Evergarden", "gender": "female", "rarity": "legendary"},
            {"name": "Gilbert Bougainvillea", "anime": "Violet Evergarden", "gender": "male", "rarity": "epic"},
            {"name": "Claudia Hodgins", "anime": "Violet Evergarden", "gender": "male", "rarity": "rare"},

            # Ergo Proxy
            {"name": "Re-l Mayer", "anime": "Ergo Proxy", "gender": "female", "rarity": "epic"},
            {"name": "Vincent Law", "anime": "Ergo Proxy", "gender": "male", "rarity": "epic"},

            # Akame ga Kill
            {"name": "Akame", "anime": "Akame ga Kill!", "gender": "female", "rarity": "legendary"},
            {"name": "Tatsumi", "anime": "Akame ga Kill!", "gender": "male", "rarity": "epic"},
            {"name": "Esdeath", "anime": "Akame ga Kill!", "gender": "female", "rarity": "legendary"},
            {"name": "Mine", "anime": "Akame ga Kill!", "gender": "female", "rarity": "epic"},
            {"name": "Leone", "anime": "Akame ga Kill!", "gender": "female", "rarity": "epic"},

            # Angel Beats!
            {"name": "Otonashi Yuzuru", "anime": "Angel Beats!", "gender": "male", "rarity": "epic"},
            {"name": "Kanade Tachibana", "anime": "Angel Beats!", "gender": "female", "rarity": "legendary"},
            {"name": "Yuri Nakamura", "anime": "Angel Beats!", "gender": "female", "rarity": "epic"},
            {"name": "Hinata Hideki", "anime": "Angel Beats!", "gender": "male", "rarity": "rare"},

            # Clannad
            {"name": "Tomoya Okazaki", "anime": "Clannad", "gender": "male", "rarity": "epic"},
            {"name": "Nagisa Furukawa", "anime": "Clannad", "gender": "female", "rarity": "legendary"},
            {"name": "Kyou Fujibayashi", "anime": "Clannad", "gender": "female", "rarity": "epic"},
            {"name": "Kotomi Ichinose", "anime": "Clannad", "gender": "female", "rarity": "rare"},

            # Steins;Gate
            {"name": "Rintarou Okabe", "anime": "Steins;Gate", "gender": "male", "rarity": "legendary"},
            {"name": "Kurisu Makise", "anime": "Steins;Gate", "gender": "female", "rarity": "legendary"},
            {"name": "Mayuri Shiina", "anime": "Steins;Gate", "gender": "female", "rarity": "epic"},
            {"name": "Itaru Hashida", "anime": "Steins;Gate", "gender": "male", "rarity": "rare"},

            # The Quintessential Quintuplets
            {"name": "Itsuki Nakano", "anime": "The Quintessential Quintuplets", "gender": "female", "rarity": "epic"},
            {"name": "Nino Nakano", "anime": "The Quintessential Quintuplets", "gender": "female", "rarity": "epic"},
            {"name": "Miku Nakano", "anime": "The Quintessential Quintuplets", "gender": "female", "rarity": "epic"},
            {"name": "Yotsuba Nakano", "anime": "The Quintessential Quintuplets", "gender": "female", "rarity": "epic"},
            {"name": "Ichika Nakano", "anime": "The Quintessential Quintuplets", "gender": "female", "rarity": "epic"},

            # That Time I Got Reincarnated as a Slime
            {"name": "Rimuru Tempest", "anime": "Slime Isekai", "gender": "male", "rarity": "legendary"},
            {"name": "Milim Nava", "anime": "Slime Isekai", "gender": "female", "rarity": "epic"},
            {"name": "Benimaru", "anime": "Slime Isekai", "gender": "male", "rarity": "epic"},
            {"name": "Shion", "anime": "Slime Isekai", "gender": "female", "rarity": "epic"},
            {"name": "Shuna", "anime": "Slime Isekai", "gender": "female", "rarity": "rare"},

            # Konosuba
            {"name": "Kazuma Satou", "anime": "Konosuba", "gender": "male", "rarity": "epic"},
            {"name": "Aqua", "anime": "Konosuba", "gender": "female", "rarity": "legendary"},
            {"name": "Megumin", "anime": "Konosuba", "gender": "female", "rarity": "legendary"},
            {"name": "Darkness", "anime": "Konosuba", "gender": "female", "rarity": "epic"},

            # ReLIFE
            {"name": "Arata Kaizaki", "anime": "ReLIFE", "gender": "male", "rarity": "epic"},
            {"name": "Chizuru Hishiro", "anime": "ReLIFE", "gender": "female", "rarity": "epic"},
            {"name": "Rena Kariu", "anime": "ReLIFE", "gender": "female", "rarity": "rare"},
            {"name": "Kazuomi Oga", "anime": "ReLIFE", "gender": "male", "rarity": "rare"},

            # A Silent Voice
            {"name": "Shouya Ishida", "anime": "A Silent Voice", "gender": "male", "rarity": "epic"},
            {"name": "Shouko Nishimiya", "anime": "A Silent Voice", "gender": "female", "rarity": "legendary"},
            {"name": "Naoka Ueno", "anime": "A Silent Voice", "gender": "female", "rarity": "rare"},

            # Your Lie in April
            {"name": "Kousei Arima", "anime": "Your Lie in April", "gender": "male", "rarity": "epic"},
            {"name": "Kaori Miyazono", "anime": "Your Lie in April", "gender": "female", "rarity": "legendary"},
            {"name": "Tsubaki Sawabe", "anime": "Your Lie in April", "gender": "female", "rarity": "rare"},

            # Horimiya
            {"name": "Izumi Miyamura", "anime": "Horimiya", "gender": "male", "rarity": "epic"},
            {"name": "Kyouko Hori", "anime": "Horimiya", "gender": "female", "rarity": "epic"},
            {"name": "Yuki Yoshikawa", "anime": "Horimiya", "gender": "female", "rarity": "rare"},
            {"name": "Toru Ishikawa", "anime": "Horimiya", "gender": "male", "rarity": "rare"},

            # Fate Series (Fate/Stay Night, Fate/Zero, Fate/Grand Order)
            {"name": "Saber (Artoria Pendragon)", "anime": "Fate Series", "gender": "female", "rarity": "legendary"},
            {"name": "Emiya Shirou", "anime": "Fate Series", "gender": "male", "rarity": "epic"},
            {"name": "Rin Tohsaka", "anime": "Fate Series", "gender": "female", "rarity": "epic"},
            {"name": "Illyasviel von Einzbern", "anime": "Fate Series", "gender": "female", "rarity": "epic"},
            {"name": "Gilgamesh", "anime": "Fate Series", "gender": "male", "rarity": "legendary"},
            {"name": "Kirei Kotomine", "anime": "Fate Series", "gender": "male", "rarity": "rare"},
            {"name": "Iskandar (Rider)", "anime": "Fate/Zero", "gender": "male", "rarity": "legendary"},
            {"name": "Mash Kyrielight", "anime": "Fate/Grand Order", "gender": "female", "rarity": "epic"},

            # Studio Ghibli
            {"name": "Chihiro Ogino", "anime": "Spirited Away", "gender": "female", "rarity": "legendary"},
            {"name": "Haku", "anime": "Spirited Away", "gender": "male", "rarity": "epic"},
            {"name": "Howl", "anime": "Howl's Moving Castle", "gender": "male", "rarity": "legendary"},
            {"name": "Sophie Hatter", "anime": "Howl's Moving Castle", "gender": "female", "rarity": "epic"},
            {"name": "Kiki", "anime": "Kiki's Delivery Service", "gender": "female", "rarity": "legendary"},
            {"name": "San", "anime": "Princess Mononoke", "gender": "female", "rarity": "legendary"},
            {"name": "Ashitaka", "anime": "Princess Mononoke", "gender": "male", "rarity": "epic"},
            {"name": "Pazu", "anime": "Castle in the Sky", "gender": "male", "rarity": "epic"},
            {"name": "Sheeta", "anime": "Castle in the Sky", "gender": "female", "rarity": "epic"},

            # Tokyo Revengers
            {"name": "Takemichi Hanagaki", "anime": "Tokyo Revengers", "gender": "male", "rarity": "epic"},
            {"name": "Manjiro Sano (Mikey)", "anime": "Tokyo Revengers", "gender": "male", "rarity": "legendary"},
            {"name": "Draken", "anime": "Tokyo Revengers", "gender": "male", "rarity": "epic"},
            {"name": "Keisuke Baji", "anime": "Tokyo Revengers", "gender": "male", "rarity": "epic"},
            {"name": "Emma Sano", "anime": "Tokyo Revengers", "gender": "female", "rarity": "rare"},

            # Gintama
            {"name": "Gintoki Sakata", "anime": "Gintama", "gender": "male", "rarity": "legendary"},
            {"name": "Shinpachi Shimura", "anime": "Gintama", "gender": "male", "rarity": "rare"},
            {"name": "Kagura", "anime": "Gintama", "gender": "female", "rarity": "epic"},
            {"name": "Toshiro Hijikata", "anime": "Gintama", "gender": "male", "rarity": "epic"},
            {"name": "Sogo Okita", "anime": "Gintama", "gender": "male", "rarity": "epic"},

            # Black Butler
            {"name": "Ciel Phantomhive", "anime": "Black Butler", "gender": "male", "rarity": "epic"},
            {"name": "Sebastian Michaelis", "anime": "Black Butler", "gender": "male", "rarity": "legendary"},
            {"name": "Grell Sutcliff", "anime": "Black Butler", "gender": "male", "rarity": "epic"},
            {"name": "Elizabeth Midford", "anime": "Black Butler", "gender": "female", "rarity": "rare"},

            # Devilman Crybaby
            {"name": "Akira Fudo", "anime": "Devilman Crybaby", "gender": "male", "rarity": "legendary"},
            {"name": "Ryo Asuka", "anime": "Devilman Crybaby", "gender": "male", "rarity": "legendary"},
            {"name": "Miki Makimura", "anime": "Devilman Crybaby", "gender": "female", "rarity": "epic"},

            # Parasyte: The Maxim
            {"name": "Shinichi Izumi", "anime": "Parasyte", "gender": "male", "rarity": "epic"},
            {"name": "Migi", "anime": "Parasyte", "gender": "male", "rarity": "epic"},
            {"name": "Satomi Murano", "anime": "Parasyte", "gender": "female", "rarity": "rare"},

            # Hellsing Ultimate
            {"name": "Alucard", "anime": "Hellsing", "gender": "male", "rarity": "legendary"},
            {"name": "Integra Hellsing", "anime": "Hellsing", "gender": "female", "rarity": "epic"},
            {"name": "Seras Victoria", "anime": "Hellsing", "gender": "female", "rarity": "epic"},

            # Danganronpa (Anime)
            {"name": "Makoto Naegi", "anime": "Danganronpa", "gender": "male", "rarity": "epic"},
            {"name": "Kyoko Kirigiri", "anime": "Danganronpa", "gender": "female", "rarity": "epic"},
            {"name": "Junko Enoshima", "anime": "Danganronpa", "gender": "female", "rarity": "legendary"},

            # Dr. Stone
            {"name": "Senku Ishigami", "anime": "Dr. Stone", "gender": "male", "rarity": "legendary"},
            {"name": "Taiju Oki", "anime": "Dr. Stone", "gender": "male", "rarity": "epic"},
            {"name": "Yuzuriha Ogawa", "anime": "Dr. Stone", "gender": "female", "rarity": "rare"},
            {"name": "Tsukasa Shishio", "anime": "Dr. Stone", "gender": "male", "rarity": "epic"},
            
            # Adding more common rarity characters
            {"name": "Konohamaru", "anime": "Naruto", "gender": "male", "rarity": "common"},
            {"name": "Tenten", "anime": "Naruto", "gender": "female", "rarity": "common"},
            {"name": "Kiba Inuzuka", "anime": "Naruto", "gender": "male", "rarity": "common"},
            {"name": "Shino Aburame", "anime": "Naruto", "gender": "male", "rarity": "common"},
            {"name": "Ino Yamanaka", "anime": "Naruto", "gender": "female", "rarity": "common"},
            
            {"name": "Chopper", "anime": "One Piece", "gender": "male", "rarity": "rare"},
            {"name": "Usopp", "anime": "One Piece", "gender": "male", "rarity": "rare"},
            {"name": "Franky", "anime": "One Piece", "gender": "male", "rarity": "rare"},
            {"name": "Brook", "anime": "One Piece", "gender": "male", "rarity": "rare"},
            {"name": "Jinbe", "anime": "One Piece", "gender": "male", "rarity": "epic"},
            
            {"name": "Krillin", "anime": "Dragon Ball Z", "gender": "male", "rarity": "common"},
            {"name": "Tien", "anime": "Dragon Ball Z", "gender": "male", "rarity": "common"},
            {"name": "Yamcha", "anime": "Dragon Ball Z", "gender": "male", "rarity": "common"},
            {"name": "Piccolo", "anime": "Dragon Ball Z", "gender": "male", "rarity": "epic"},
            {"name": "Chi-Chi", "anime": "Dragon Ball Z", "gender": "female", "rarity": "common"},
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