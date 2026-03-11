#!/bin/bash

# Function to handle SIGINT gracefully
handle_interrupt() {
    echo "Ctrl+C received. Stopping monitoring."
    exit 0 # Exit with a success status
}

# Register the interrupt handler function
trap 'handle_interrupt' INT

while true; do
    sudo vcgencmd measure_temp
    echo "Current CPU Temperature: `sudo vcgencmd measure_temp`"
    
    sleep 3 # Adjust the interval as needed (e.g., 60 seconds)
done
