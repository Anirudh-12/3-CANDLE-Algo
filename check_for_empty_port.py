import socket

def is_port_available(port, host='localhost'):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True  # Port is available
        except OSError:
            return False  # Port is in use

def check_for_empty_port(start_port=5005, end_port=6000, host='localhost'):
    for port in range(start_port, end_port + 1):
        if is_port_available(port, host):
            return port
    return None  # No available port found in the range
# Example usage
if __name__ == "__main__":
    available_port = check_for_empty_port()
    if available_port:
        print(f"Available port found: {available_port}")
    else:
        print("No available port found in the specified range.")
