from slowapi import Limiter
from slowapi.util import get_remote_address

# Initialize the Limiter. 
# get_remote_address securely fetches the user's IP address to track their requests.
limiter = Limiter(key_func=get_remote_address)