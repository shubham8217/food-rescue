ROLE_DONOR = "donor"
ROLE_NGO = "ngo"
ROLE_ADMIN = "admin"

# Donation status flow: listed -> matched -> accepted -> picked_up -> delivered
S_LISTED = "listed"
S_MATCHED = "matched"
S_ACCEPTED = "accepted"
S_PICKED_UP = "picked_up"
S_DELIVERED = "delivered"
S_EXPIRED = "expired"  # side exit: nobody took it in time

NEXT_STATUS = {
    S_LISTED: S_MATCHED,
    S_MATCHED: S_ACCEPTED,
    S_ACCEPTED: S_PICKED_UP,
    S_PICKED_UP: S_DELIVERED,
}

CATEGORIES = ["cooked_meals", "bakery", "produce", "dairy", "packaged", "beverages"]

QUEUE_DONATION_CREATED = "donation.created"

MEAL_KG = 0.4  # 1 meal ~= 0.4 kg of food
